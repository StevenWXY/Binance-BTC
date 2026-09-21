"""Cache original monthly Binance futures data; audit gaps, never forward-fill.

Local data/raw archives are read only. Optional --repair downloads official
daily mark-price archives, checks published SHA256, and overlays missing rows.
Only complete monthly archives before the fixed research end are consumed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from btc_regime.data import load_funding, load_ohlc_archive

END = pd.Timestamp("2026-08-01", tz="UTC")


def prepare(raw: Path, cache: Path, repair: bool) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "minutes").mkdir(exist_ok=True)
    (cache / "repair").mkdir(exist_ok=True)
    hourly, audit = [], []
    for month in pd.period_range("2020-01", "2026-07", freq="M"):
        name = f"BTCUSDT-1m-{month}.zip"
        paths = [raw / "klines" / name, raw / "mark_price" / name]
        trade, mark = [load_ohlc_archive(p) for p in paths]
        start = month.start_time.tz_localize("UTC")
        end = (month + 1).start_time.tz_localize("UTC")
        expected = pd.date_range(start, end, freq="min", inclusive="left")
        provenance = []
        missing = expected.difference(mark.index)
        if repair:
            for day in sorted(set(missing.strftime("%Y-%m-%d"))):
                filename = f"BTCUSDT-1m-{day}.zip"
                url = f"https://data.binance.vision/data/futures/um/daily/markPriceKlines/BTCUSDT/1m/{filename}"
                target = cache / "repair" / filename
                checksum = target.with_suffix(".zip.CHECKSUM")
                if not target.exists():
                    target.write_bytes(urlopen(url, timeout=30).read())
                if not checksum.exists():
                    checksum.write_bytes(urlopen(url + ".CHECKSUM", timeout=30).read())
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if digest != checksum.read_text().split()[0]:
                    raise ValueError(f"checksum mismatch: {filename}")
                extra = load_ohlc_archive(target)
                # Preserve observed original marks; only insert absent timestamps.
                mark = pd.concat([mark, extra.loc[~extra.index.isin(mark.index)]]).sort_index()
                provenance.append({"url": url, "sha256": digest})
        joined = trade.add_prefix("trade_").join(mark[["open", "high", "low", "close"]].add_prefix("mark_"), how="inner")
        joined.to_pickle(cache / "minutes" / f"{month}.pkl")
        aggregate = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "quote_volume": "sum"}
        h = trade.resample("1h").agg(aggregate)
        h["minute_count"] = trade.close.resample("1h").count()
        if h.isna().any().any():
            raise ValueError(f"missing hourly trade candle in {month}")
        hm = mark.resample("1h").agg({k: v for k, v in aggregate.items() if k in {"open", "high", "low", "close"}})
        h = h.join(hm.add_prefix("mark_"))
        hourly.append(h)
        audit.append({"month": str(month), "expected_minutes": len(expected), "trade_minutes": len(trade),
                      "paired_minutes": len(joined), "missing_mark_before": len(missing),
                      "missing_paired_minutes": len(expected.difference(joined.index)),
                      "incomplete_trade_hours": int(h.minute_count.ne(60).sum()),
                      "repair_sources": provenance,
                      "local_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
        if month.month in {1, 7}:
            print(str(month), "missing paired", audit[-1]["missing_paired_minutes"], flush=True)
    data = pd.concat(hourly)
    funding = load_funding(raw, start="2020-01-01", end=END.isoformat())
    rates = funding.funding_rate.groupby(funding.index.floor("1h")).sum()
    data["funding_rate"] = rates.reindex(data.index, fill_value=0)
    data["funding_event"] = data.index.isin(rates.index)
    data.to_pickle(cache / "hourly.pkl")
    funding.to_pickle(cache / "funding.pkl")
    output = Path("reports/v4_4_1")
    output.mkdir(exist_ok=True, parents=True)
    payload = {"start": str(data.index[0]), "end_exclusive": str(END), "hourly_rows": len(data),
               "funding_events": len(funding), "funding_months": sorted(set(funding.index.strftime("%Y-%m"))),
               "original_archives_modified": False, "repair_enabled": repair, "months": audit}
    (output / "data_audit.json").write_text(json.dumps(payload, indent=2) + "\n")
    print("complete", len(data), "hours; missing paired minutes", sum(a["missing_paired_minutes"] for a in audit), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--cache", type=Path, default=Path("data/v441"))
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    prepare(args.raw_dir, args.cache, args.repair)

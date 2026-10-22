"""Download Bitget BTCUSDT perpetual candles and the available funding history.

Bitget's public historical-candle endpoint accepts at most 200 rows for the
five-minute interval used here.  The downloader shards the time range into
independent requests so an interrupted run can resume from the cached JSON
pages.  Market candles are used for simulated fills and mark candles for
mark-to-market, stops, and liquidation checks.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
import time
import urllib.parse
import urllib.request

import pandas as pd


BASE = "https://api.bitget.com/api/v2/mix/market"
COLS = ["timestamp", "open", "high", "low", "close", "base_volume", "quote_volume"]
REQUEST_LOCK = Lock()
NEXT_REQUEST_AT = 0.0
# Stay comfortably below Bitget's documented public market-data rate limit.
REQUEST_INTERVAL_SECONDS = 0.09


def wait_for_request_slot() -> None:
    global NEXT_REQUEST_AT
    with REQUEST_LOCK:
        now = time.monotonic()
        delay = max(0.0, NEXT_REQUEST_AT - now)
        NEXT_REQUEST_AT = max(now, NEXT_REQUEST_AT) + REQUEST_INTERVAL_SECONDS
    if delay:
        time.sleep(delay)


def apply_rate_limit_cooldown(seconds: float) -> None:
    global NEXT_REQUEST_AT
    with REQUEST_LOCK:
        NEXT_REQUEST_AT = max(NEXT_REQUEST_AT, time.monotonic() + seconds)


def request_json(endpoint: str, params: dict[str, str], retries: int = 5) -> dict:
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(retries):
        try:
            wait_for_request_slot()
            with urllib.request.urlopen(url, timeout=60) as response:
                payload = json.loads(response.read().decode())
            if payload.get("code") != "00000":
                raise RuntimeError(f"Bitget {endpoint}: {payload}")
            return payload
        except Exception as exc:  # network and rate-limit responses are transient
            last = exc
            if getattr(exc, "code", None) == 429:
                apply_rate_limit_cooldown(20.0)
                time.sleep(20.0)
            else:
                time.sleep(min(2.0 * (attempt + 1), 10.0))
    raise RuntimeError(f"request failed after retries: {url}") from last


def page_jobs(start: pd.Timestamp, end: pd.Timestamp, interval_minutes: int) -> list[tuple[int, int]]:
    step = interval_minutes * 60_000 * 200
    first = int(start.timestamp() * 1000)
    last = int(end.timestamp() * 1000)
    return [(cursor, min(cursor + step, last)) for cursor in range(first, last, step)]


def fetch_page(endpoint: str, cursor: tuple[int, int], cache: Path, interval: str) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    first, last = cursor
    path = cache / f"{first}_{last}.json"
    if path.exists():
        return path
    payload = request_json(endpoint, {
        "symbol": "BTCUSDT", "productType": "USDT-FUTURES", "granularity": interval,
        "limit": "200", "startTime": str(first), "endTime": str(last),
    })
    path.write_text(json.dumps(payload))
    return path


def read_pages(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        rows.extend(json.loads(path.read_text()).get("data", []))
    if not rows:
        raise RuntimeError("Bitget returned no candle rows")
    frame = pd.DataFrame(rows, columns=COLS)
    frame["timestamp"] = pd.to_datetime(frame.timestamp.astype("int64"), unit="ms", utc=True)
    for col in COLS[1:]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    return frame.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")


def download_candles(start: pd.Timestamp, end: pd.Timestamp, out: Path, workers: int) -> pd.DataFrame:
    interval = "5m"
    jobs = page_jobs(start, end, 5)
    paths: dict[str, list[Path]] = {"market": [], "mark": []}
    for kind, endpoint in (("market", "history-candles"), ("mark", "history-mark-candles")):
        cache = out / "pages" / kind
        all_paths = [cache / f"{first}_{last}.json" for first, last in jobs]
        pending = [job for job, path in zip(jobs, all_paths) if not path.exists()]
        for retry_round in range(1, 11):
            if not pending:
                break
            failed: list[tuple[int, int]] = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(fetch_page, endpoint, job, cache, interval): job for job in pending}
                for i, future in enumerate(as_completed(futures), 1):
                    job = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        failed.append(job)
                        print(f"{kind}: page {job[0]} failed on retry {retry_round}: {exc}", flush=True)
                    if i % 250 == 0 or i == len(futures):
                        print(f"{kind}: {i}/{len(futures)} pending pages", flush=True)
            pending = failed
            if pending:
                time.sleep(min(10.0 * retry_round, 60.0))
        if pending:
            raise RuntimeError(f"{kind}: unable to download {len(pending)} pages after retries")
        paths[kind] = all_paths
        print(f"{kind}: {len(all_paths)}/{len(all_paths)} pages cached", flush=True)
    market = read_pages(paths["market"]).add_prefix("trade_")
    mark = read_pages(paths["mark"]).add_prefix("mark_")
    frame = market.join(mark, how="inner").loc[(market.index >= start) & (market.index < end)]
    frame.to_pickle(out / "candles_5m.pkl")
    frame.to_csv(out / "candles_5m.csv.gz", compression="gzip")
    return frame


def download_funding(start: pd.Timestamp, end: pd.Timestamp, out: Path) -> pd.DataFrame:
    # The currently documented v2 endpoint exposes the most recent 270
    # settlements (three 100-row pages).  We retain this exact coverage and
    # explicitly mark the older period as unavailable in the manifest.
    records = []
    for page in range(1, 101):
        payload = request_json("history-fund-rate", {
            "symbol": "BTCUSDT", "productType": "USDT-FUTURES", "pageSize": "100", "pageNo": str(page),
        })
        batch = payload.get("data", [])
        if not batch:
            break
        records.extend(batch)
        if len(batch) < 100:
            break
    funding = pd.DataFrame(records)
    if funding.empty:
        funding = pd.DataFrame(columns=["funding_rate"])
        funding.index = pd.DatetimeIndex([], tz="UTC")
    else:
        funding["timestamp"] = pd.to_datetime(pd.to_numeric(funding.fundingTime), unit="ms", utc=True)
        funding["funding_rate"] = pd.to_numeric(funding.fundingRate)
        funding = funding.drop_duplicates("timestamp").set_index("timestamp").sort_index()
        funding = funding[["funding_rate"]].loc[(funding.index >= start) & (funding.index < end)]
    funding.to_pickle(out / "funding.pkl")
    return funding


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--out", type=Path, default=Path("data/bitget_v4"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    args.out.mkdir(parents=True, exist_ok=True)
    candles = download_candles(start, end, args.out, max(1, args.workers))
    funding = download_funding(start, end, args.out)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "BTCUSDT", "product_type": "USDT-FUTURES", "interval": "5m",
        "requested_start": start.isoformat(), "requested_end_exclusive": end.isoformat(),
        "observed_start": candles.index.min().isoformat(), "observed_end": candles.index.max().isoformat(),
        "candle_rows": len(candles), "funding_rows": len(funding),
        "funding_observed_start": funding.index.min().isoformat() if len(funding) else None,
        "funding_observed_end": funding.index.max().isoformat() if len(funding) else None,
        "funding_missing_before_observed_start": True,
        "funding_endpoint_note": "Bitget v2 history-fund-rate returned only the available recent pages; older funding is absent from the public endpoint and is not fabricated.",
        "mark_price_source": "history-mark-candles", "trade_price_source": "history-candles",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

"""Rebuild/check the fixed August paired-minute input, without computing returns."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from btc_regime.data import load_ohlc_archive


def main():
    root = Path("reports/v4_4_1_round2")
    audit = json.loads((root / "extension_coverage.json").read_text())
    frames = []
    for kind, folder in [("trade", "klines"), ("mark", "mark_price")]:
        source = Path("data/raw") / folder / "BTCUSDT-1m-2026-08.zip"
        if hashlib.sha256(source.read_bytes()).hexdigest() != audit[kind]["sha256"]:
            raise ValueError(f"Extension archive differs from recorded input: {source}")
        frames.append(load_ohlc_archive(source))
    trade, mark = frames
    data = trade.add_prefix("trade_").join(
        mark[["open", "high", "low", "close"]].add_prefix("mark_"), how="inner")
    expected = pd.date_range("2026-08-01", "2026-09-01", inclusive="left", freq="min", tz="UTC")
    if not data.index.equals(expected):
        raise ValueError("Extension minute coverage changed")
    target = Path("data/v441/round2/extension_minutes.pkl")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        pd.testing.assert_frame_equal(data, pd.read_pickle(target), check_freq=False)
    else:
        data.to_pickle(target)
    lock = json.loads((root / "final_selection_lock.json").read_text())
    if hashlib.sha256(target.read_bytes()).hexdigest() != lock["source_sha256"][str(target)]:
        raise ValueError("Serialized cache hash changed; check Python/pandas serialization version")
    print("Verified", len(data), "paired minutes; recorded archives and frozen cache unchanged")


if __name__ == "__main__":
    main()

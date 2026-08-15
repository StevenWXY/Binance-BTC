"""Download and normalize Binance USD-M BTCUSDT historical data."""

from __future__ import annotations

import zipfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

BASE_URL = "https://data.binance.vision/data/futures/um/monthly"
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def _months(start: str, end: str) -> list[str]:
    start_period = pd.Period(start, freq="M")
    end_period = pd.Period(end, freq="M")
    if start_period > end_period:
        raise ValueError("start must be before or equal to end")
    return [str(p) for p in pd.period_range(start_period, end_period, freq="M")]


def _download(url: str, destination: Path) -> bool:
    if destination.exists() and destination.stat().st_size > 0:
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "btc-regime-research/0.1"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                destination.write_bytes(response.read())
            return True
        except HTTPError as exc:
            if exc.code == 404:
                if attempt == 2:
                    return False
                time.sleep(1.0 * (attempt + 1))
                continue
            if attempt == 2:
                raise
        except URLError:
            if attempt == 2:
                raise
        time.sleep(1.0 * (attempt + 1))
    return False


def download_binance_data(
    start: str,
    end: str,
    *,
    interval: str = "4h",
    symbol: str = "BTCUSDT",
    raw_dir: str | Path = "data/raw",
) -> dict[str, int]:
    """Download monthly official Binance files; missing early/partial months are skipped."""
    raw_path = Path(raw_dir)
    kline_count = funding_count = 0
    for month in _months(start, end):
        kline_name = f"{symbol}-{interval}-{month}.zip"
        kline_url = f"{BASE_URL}/klines/{symbol}/{interval}/{kline_name}"
        if _download(kline_url, raw_path / "klines" / kline_name):
            kline_count += 1
        funding_name = f"{symbol}-fundingRate-{month}.zip"
        funding_url = f"{BASE_URL}/fundingRate/{symbol}/{funding_name}"
        if _download(funding_url, raw_path / "funding" / funding_name):
            funding_count += 1
    return {"kline_months": kline_count, "funding_months": funding_count}


def download_intrabar_data(
    start: str,
    end: str,
    *,
    symbol: str = "BTCUSDT",
    raw_dir: str | Path = "data/raw",
    max_workers: int = 8,
) -> dict[str, int]:
    """Download 1m contract and mark-price archives concurrently."""
    raw_path = Path(raw_dir)
    jobs: list[tuple[str, str, Path]] = []
    for month in _months(start, end):
        name = f"{symbol}-1m-{month}.zip"
        jobs.extend([
            ("trade", f"{BASE_URL}/klines/{symbol}/1m/{name}", raw_path / "klines" / name),
            (
                "mark",
                f"{BASE_URL}/markPriceKlines/{symbol}/1m/{name}",
                raw_path / "mark_price" / name,
            ),
        ])
    counts = {"trade_months": 0, "mark_months": 0, "missing_files": 0}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_download, url, path): kind for kind, url, path in jobs}
        for future in as_completed(future_map):
            kind = future_map[future]
            if future.result():
                counts[f"{kind}_months"] += 1
            else:
                counts["missing_files"] += 1
    return counts


def _read_csv_from_zip(path: Path, expected_columns: list[str] | None = None) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not names:
            raise ValueError(f"no CSV found in {path}")
        with archive.open(names[0]) as handle:
            frame = pd.read_csv(handle)
        # Binance archives before the header-standardization change are headerless.
        if expected_columns and not set(expected_columns).intersection(frame.columns):
            with archive.open(names[0]) as handle:
                frame = pd.read_csv(handle, header=None, names=expected_columns)
        return frame


def load_ohlc_archive(path: str | Path) -> pd.DataFrame:
    """Load one Binance kline ZIP into a compact UTC-indexed frame."""
    frame = _read_csv_from_zip(Path(path), KLINE_COLUMNS)
    if list(frame.columns) != KLINE_COLUMNS:
        frame.columns = KLINE_COLUMNS[: len(frame.columns)]
    keep = ["open_time", "open", "high", "low", "close", "volume", "quote_volume"]
    frame = frame[keep].copy()
    frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    for column in ["open", "high", "low", "close", "volume", "quote_volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .set_index("timestamp")
        [["open", "high", "low", "close", "volume", "quote_volume"]]
    )


def load_klines(
    raw_dir: str | Path = "data/raw",
    *,
    start: str | None = None,
    end: str | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
) -> pd.DataFrame:
    """Load Binance kline archives into a UTC-indexed OHLCV frame."""
    files = sorted(Path(raw_dir, "klines").glob(f"{symbol}-{interval}-*.zip"))
    if not files:
        raise FileNotFoundError("No kline archives found; run the download command first")
    frames: list[pd.DataFrame] = []
    for path in files:
        frames.append(load_ohlc_archive(path))
    data = pd.concat(frames).sort_index().loc[lambda x: ~x.index.duplicated(keep="last")]
    if start:
        data = data.loc[data.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        end_ts = pd.Timestamp(end, tz="UTC")
        if len(str(end)) == 10:
            end_ts += pd.Timedelta(days=1)
        data = data.loc[data.index < end_ts]
    return data[["open", "high", "low", "close", "volume", "quote_volume"]]


def iter_intrabar_months(
    raw_dir: str | Path = "data/raw",
    *,
    start: str | None = None,
    end: str | None = None,
    symbol: str = "BTCUSDT",
) -> Iterator[pd.DataFrame]:
    """Yield aligned 1m contract and mark-price data one month at a time."""
    raw_path = Path(raw_dir)
    trade_files = {path.stem[-7:]: path for path in raw_path.joinpath("klines").glob(f"{symbol}-1m-*.zip")}
    mark_files = {path.stem[-7:]: path for path in raw_path.joinpath("mark_price").glob(f"{symbol}-1m-*.zip")}
    missing_trade = sorted(set(mark_files) - set(trade_files))
    missing_mark = sorted(set(trade_files) - set(mark_files))
    if missing_trade or missing_mark:
        raise FileNotFoundError(
            f"Unpaired 1m archives; missing trade={missing_trade}, missing mark={missing_mark}"
        )
    if not trade_files:
        raise FileNotFoundError("No paired 1m archives found; run download-intrabar first")
    start_ts = pd.Timestamp(start, tz="UTC") if start else None
    end_ts = pd.Timestamp(end, tz="UTC") if end else None
    for month in sorted(trade_files):
        trade = load_ohlc_archive(trade_files[month]).add_prefix("trade_")
        mark = load_ohlc_archive(mark_files[month])[["open", "high", "low", "close"]].add_prefix("mark_")
        data = trade.join(mark, how="inner")
        if start_ts is not None:
            data = data.loc[data.index >= start_ts]
        if end_ts is not None:
            data = data.loc[data.index < end_ts]
        if not data.empty:
            yield data


def load_funding(
    raw_dir: str | Path = "data/raw",
    *,
    start: str | None = None,
    end: str | None = None,
    symbol: str = "BTCUSDT",
) -> pd.DataFrame:
    """Load the official funding-rate event series."""
    files = sorted(Path(raw_dir, "funding").glob(f"{symbol}-fundingRate-*.zip"))
    if not files:
        raise FileNotFoundError("No funding archives found; run the download command first")
    expected = ["calc_time", "funding_interval_hours", "last_funding_rate"]
    frames = [_read_csv_from_zip(path, expected) for path in files]
    data = pd.concat(frames, ignore_index=True)
    data["timestamp"] = pd.to_datetime(data["calc_time"], unit="ms", utc=True)
    data["funding_rate"] = pd.to_numeric(data["last_funding_rate"], errors="coerce")
    data = data.dropna(subset=["timestamp", "funding_rate"])
    data = data.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    if start:
        data = data.loc[data.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        end_ts = pd.Timestamp(end, tz="UTC")
        if len(str(end)) == 10:
            end_ts += pd.Timedelta(days=1)
        data = data.loc[data.index < end_ts]
    return data[["funding_rate"]]


def merge_funding(klines: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """Attach funding events to the kline open at which they are charged."""
    result = klines.copy()
    # Funding timestamps can be a few milliseconds after the exact 8-hour boundary.
    events = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    result["funding_rate"] = events.reindex(result.index, fill_value=0.0)
    return result


def load_market_data(
    raw_dir: str | Path = "data/raw",
    *,
    start: str | None = None,
    end: str | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "4h",
) -> pd.DataFrame:
    klines = load_klines(raw_dir, start=start, end=end, symbol=symbol, interval=interval)
    funding = load_funding(raw_dir, start=start, end=end, symbol=symbol)
    return merge_funding(klines, funding)

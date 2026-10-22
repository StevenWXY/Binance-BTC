from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v461 import generate_v461_signals
from btc_regime.v462 import V462Params, generate_v462_signals


def execution_fixture(highs, lows, opens=None, side=1):
    n = len(highs)
    idx = pd.date_range("2024-01-01 01:00", periods=n, freq="5min", tz="UTC")
    raw = pd.DataFrame(index=idx)
    for prefix in ("trade", "mark"):
        raw[f"{prefix}_open"] = opens if opens is not None else [100.] * n
        raw[f"{prefix}_close"] = raw[f"{prefix}_open"]
        raw[f"{prefix}_high"] = highs
        raw[f"{prefix}_low"] = lows
    raw["trade_volume"] = 1e6
    raw["trade_quote_volume"] = 1e8
    signals = pd.DataFrame({"signal": [side], "cycle_id": ["one"]},
                           index=pd.DatetimeIndex([idx[0] - pd.Timedelta(hours=1)]))
    funding = pd.DataFrame({"funding_rate": []}, index=pd.DatetimeIndex([], tz="UTC"))
    cfg = MicroBacktestConfig(maker_enabled=True, maker_resting_mode=True, maker_offset_bps=10.,
                              maker_fill_penetration_bps=1., maker_timeout_taker=True,
                              maker_order_timeout_minutes=15, signal_interval_minutes=60,
                              execution_bar_minutes=5, equity_interval_minutes=5,
                              taker_fee_bps=2.4, maker_fee_bps=0.8)
    return signals, raw, funding, cfg


def test_resting_maker_does_not_fill_placement_bar_and_keeps_quote():
    signal, raw, funding, cfg = execution_fixture([100.1, 101.1, 101.1], [99., 99.8, 100.9], [100., 101., 101.])
    r = run_micro_backtest(signal, [raw], funding, cfg)
    fill = r.fills.loc[r.fills.reason.eq("signal")].iloc[0]
    assert fill.timestamp == raw.index[1]
    assert fill.price == pytest.approx(99.9)  # original quote, not 100.899
    assert fill.quantity == pytest.approx(100.)  # original target, not resized on later prices
    assert fill.fee / fill.notional == pytest.approx(0.00008)


def test_resting_maker_requires_penetration_and_times_out_to_taker():
    signal, raw, funding, cfg = execution_fixture([100.2] * 5, [99.9] * 5)
    r = run_micro_backtest(signal, [raw], funding, cfg)
    fill = r.fills.loc[r.fills.reason.eq("signal")].iloc[0]
    assert fill.timestamp == raw.index[3]
    assert fill.liquidity == "taker"
    assert r.metrics["maker_timeout_fallback_count"] == 1
    assert fill.fee / fill.notional == pytest.approx(0.00024)


def test_resting_maker_cancel_means_no_fill_even_on_expiry_touch():
    signal, raw, funding, cfg = execution_fixture([100.2] * 5, [100., 100., 100., 99., 99.])
    r = run_micro_backtest(signal, [raw], funding, replace(cfg, maker_timeout_taker=False))
    assert r.fills.empty
    assert r.metrics["maker_cancel_count"] == 1
    assert r.metrics["maker_order_count"] == 1


def test_resting_sell_symmetric_and_protective_stop_is_taker():
    signal, raw, funding, cfg = execution_fixture([100., 100.2, 102.], [99.8] * 3, side=-1)
    signal["stop_price"] = 101.
    signal["take_profit_price"] = 95.
    r = run_micro_backtest(signal, [raw], funding, cfg)
    opening = r.fills.iloc[0]
    assert opening.timestamp == raw.index[1]
    assert opening.price == pytest.approx(100.1)
    assert opening.liquidity == "maker"
    stop = r.fills.loc[r.fills.reason.eq("stop_loss")].iloc[0]
    assert stop.liquidity == "taker"


def test_resting_partial_fills_respect_capacity_and_fixed_target():
    signal, raw, funding, cfg = execution_fixture([100.2] * 5, [99.7] * 5)
    raw["trade_quote_volume"] = 400_000.
    cfg = replace(cfg, maker_fill_capacity_fraction=.25)
    r = run_micro_backtest(signal, [raw], funding, cfg)
    fills = r.fills.loc[r.fills.reason.eq("signal")]
    assert fills.liquidity.tolist() == ["maker", "maker", "taker"]
    assert fills.quantity.tolist() == pytest.approx([20., 20., 60.])
    assert fills.position_after.iloc[-1] == pytest.approx(100.)
    assert fills.iloc[-1].timestamp == raw.index[3]


def test_risk_reduction_executes_taker_without_passive_delay():
    signal, raw, funding, cfg = execution_fixture([100.2] * 15, [99.7] * 15)
    signal.loc[raw.index[0], ["signal", "cycle_id"]] = [0., "two"]
    r = run_micro_backtest(signal, [raw], funding, cfg)
    fills = r.fills.loc[r.fills.reason.eq("signal")]
    assert fills.iloc[0].liquidity == "maker"
    exit_ = fills.iloc[1]
    assert exit_.timestamp == raw.index[12]
    assert exit_.liquidity == "taker"
    assert exit_.position_after == 0.


def test_exact_month_boundaries_include_first_month_and_exclude_partial():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from research_v462 import complete_months
    equity = pd.Series([100., 110., 99., 102.],
                       index=pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-03-15"], utc=True))
    monthly = complete_months(equity)
    assert monthly.index.tolist() == equity.index[:2].tolist()
    assert monthly.tolist() == pytest.approx([.10, -.10])


def test_selective_maker_keeps_entry_taker_and_only_adds_passively():
    signal, raw, funding, cfg = execution_fixture([100.2] * 16, [99.7] * 16)
    signal.loc[raw.index[0], ["signal", "cycle_id"]] = [2., "one"]
    r = run_micro_backtest(signal, [raw], funding, replace(cfg, maker_new_position_enabled=False))
    fills = r.fills.loc[r.fills.reason.eq("signal")]
    assert fills.iloc[0].timestamp == raw.index[0]
    assert fills.iloc[0].liquidity == "taker"
    assert fills.iloc[1].timestamp == raw.index[13]
    assert fills.iloc[1].liquidity == "maker"


def test_zero_volume_at_expiry_does_not_lose_taker_fallback():
    signal, raw, funding, cfg = execution_fixture([100.2] * 5, [100.] * 5)
    raw.loc[raw.index[3], "trade_quote_volume"] = 0.
    r = run_micro_backtest(signal, [raw], funding, cfg)
    fill = r.fills.loc[r.fills.reason.eq("signal")].iloc[0]
    assert fill.timestamp == raw.index[4]
    assert fill.liquidity == "taker"
    assert r.metrics["maker_timeout_fallback_count"] == 1


def test_v462_parameter_roundtrip_preserves_nested_strategy():
    params = V462Params()
    params = replace(params, long=replace(params.long, breakout_hours=4),
                     risk=replace(params.risk, exposure_scale=.85))
    assert V462Params.from_dict(params.to_dict()) == params


def trending_market(n=3000):
    idx = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(12)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(.0004, .006, n))), index=idx)
    return pd.DataFrame({"open": close.shift().fillna(close.iloc[0]), "high": close * 1.01,
                         "low": close * .99, "close": close, "volume": 1e5,
                         "quote_volume": 1e7, "funding_rate": 0., "funding_event": False})


def test_v462_control_matches_v461_and_changed_entry_is_prefix_causal():
    data = trending_market()
    control = generate_v462_signals(data)
    baseline = generate_v461_signals(data)
    cols = ["signal", "stop_price", "take_profit_price", "cycle_id"]
    pd.testing.assert_frame_equal(control[cols], baseline[cols])
    p = V462Params()
    p = replace(p, long=replace(p.long, breakout_hours=4))
    full = generate_v462_signals(data, p)
    prefix = generate_v462_signals(data.iloc[:2401], p)
    pd.testing.assert_frame_equal(full.loc[prefix.index, cols], prefix[cols])
    assert full.signal.ne(0).any()

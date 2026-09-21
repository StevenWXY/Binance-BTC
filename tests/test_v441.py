from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441 import V441Params, core_params, generate_v441_signals, v441_features
from btc_regime.v441_research import daily_equity, candidate_grid, select


def market(n=3600):
    rng = np.random.default_rng(441)
    close = 100 * np.exp(np.cumsum(rng.normal(-.0002, .004, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "high": np.maximum(op, close) * 1.002,
                         "low": np.minimum(op, close) * .998, "close": close,
                         "volume": 10000., "quote_volume": 1e8, "funding_rate": 0.,
                         "funding_event": False},
                        index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"))


def test_completed_higher_timeframes_are_causal():
    data = market()
    params = V441Params()
    full = generate_v441_signals(data, params)
    # Cut within a 4h candle and before daily close.
    prefix = generate_v441_signals(data.iloc[:3002], params)
    pd.testing.assert_frame_equal(full.iloc[:3002], prefix)
    modified = data.copy()
    modified.iloc[3002:, :4] *= 1.7
    changed = generate_v441_signals(modified, params)
    pd.testing.assert_frame_equal(full.iloc[:3002], changed.iloc[:3002])
    f = v441_features(data, params)
    assert f.loc["2024-04-20 00:00":"2024-04-20 22:00", "daily_close"].nunique() == 1
    assert f.loc["2024-04-20 23:00", "daily_close"] == data.loc["2024-04-20 23:00", "close"]


def test_risk_caps_short_filter_and_monotone_stops():
    p = V441Params()
    signals = generate_v441_signals(market(), p)
    assert signals.signal.max() <= p.max_leverage
    assert signals.signal.min() >= -p.short_max_leverage
    shorts = signals.v441_event.eq("short_entry")
    assert shorts.any()
    assert signals.loc[shorts, "bear"].all()
    assert (signals.loc[shorts, "known_funding"] > -p.funding_crowded).all()
    for _, cycle in signals.loc[signals.signal.ne(0)].groupby("cycle_id"):
        direction = np.sign(cycle.signal.iloc[0])
        assert (cycle.stop_price.diff().dropna() * direction >= -1e-10).all()
    long_only = generate_v441_signals(market(), replace(p, short_enabled=False))
    assert (long_only.signal >= 0).all()


def test_zero_funding_event_replaces_previous_crowding():
    data = market(500)
    data.iloc[300, data.columns.get_loc("funding_rate")] = .001
    data.iloc[[300, 308], data.columns.get_loc("funding_event")] = True
    features = v441_features(data, V441Params())
    assert features.known_funding.iloc[307] == .001
    assert features.known_funding.iloc[308] == 0


def test_rejects_missing_hours_and_respects_flat_split_start():
    data = market()
    with pytest.raises(ValueError, match="continuous"):
        generate_v441_signals(data.drop(data.index[100]))
    start = "2024-04-01"
    s = generate_v441_signals(data, trade_start=start)
    assert s.loc[s.index + pd.Timedelta(hours=1) < pd.Timestamp(start, tz="UTC"), "signal"].eq(0).all()


def minute_frame(index, prices):
    result = pd.DataFrame(index=index)
    for kind in ["trade", "mark"]:
        for suffix in ["open", "close", "high", "low"]:
            result[f"{kind}_{suffix}"] = prices
    result["trade_volume"] = 1e6
    result["trade_quote_volume"] = 1e8
    return result


def test_hourly_execution_delay_and_funding_order():
    start = pd.Timestamp("2024-01-01", tz="UTC")
    signal = pd.DataFrame({"signal": [1.]}, index=[start])
    minutes = minute_frame(pd.date_range(start + pd.Timedelta(minutes=59), periods=3, freq="min"), 100.)
    funding = pd.DataFrame({"funding_rate": [.001]}, index=[start + pd.Timedelta(hours=1)])
    result = run_micro_backtest(signal, [minutes], funding,
                                MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=1))
    assert result.fills.iloc[0].timestamp == start + pd.Timedelta(hours=1)
    assert result.metrics["funding_paid"] == 0  # event precedes new entry
    assert result.equity.index[-1] == start + pd.Timedelta(minutes=62)


@pytest.mark.parametrize("side,gap,stop", [(1., 80., 95.), (-1., 120., 105.)])
def test_stop_gap_and_cycle_reentry_lock(side, gap, stop):
    start = pd.Timestamp("2024-01-01", tz="UTC")
    signal = pd.DataFrame({"signal": [side, side * .8], "cycle_id": ["a", "a"],
                           "stop_price": [stop, stop], "take_profit_price": [np.nan, np.nan]},
                          index=[start, start + pd.Timedelta(hours=1)])
    index = pd.DatetimeIndex([start + pd.Timedelta(hours=1), start + pd.Timedelta(minutes=61),
                              start + pd.Timedelta(hours=2)])
    minutes = minute_frame(index, [100., gap, gap])
    funding = pd.DataFrame({"funding_rate": []}, index=pd.DatetimeIndex([], tz="UTC"))
    result = run_micro_backtest(signal, [minutes], funding, MicroBacktestConfig(
        signal_interval_minutes=60, equity_interval_minutes=1, conservative_protection=True))
    exits = result.fills.loc[result.fills.reason.eq("stop_loss")]
    assert len(exits) == 1
    assert exits.price.iloc[0] < gap if side > 0 else exits.price.iloc[0] > gap
    assert len(result.trades) == 1
    assert result.fills.iloc[-1].timestamp < start + pd.Timedelta(hours=2)


def test_daily_metrics_keep_midnight_initial_equity():
    equity = pd.Series([100, 110, 121], index=pd.date_range("2024-01-01", periods=3, freq="12h", tz="UTC"))
    daily = daily_equity(equity)
    assert daily.tolist() == [100, 121]


def test_selection_rejects_short_overfit_despite_high_score():
    params = candidate_grid()[0].to_dict()
    part = {"sharpe": 1., "annual_log_growth": .2, "max_drawdown": -.2, "cycles": 30,
            "short_cycles": 0, "short_sum_trade_returns": 0., "total_return": .2}
    rows = [{"id": "long", "params": params,
             "periods": {k: dict(part) for k in ["legacy", "recent_train", "recent_validation"]}},
            {"id": "short", "params": {**params, "short_enabled": True},
             "periods": {k: {**part, "sharpe": 5.} for k in ["legacy", "recent_train", "recent_validation"]}}]
    assert select(rows)["id"] == "long"


def test_core_profile_matches_existing_version_and_router_is_causal():
    import json
    from pathlib import Path
    baseline = json.loads((Path(__file__).resolve().parents[1] / "configs/v4_1_2_params.json").read_text())
    assert core_params().to_dict() == baseline
    data = market()
    p = V441Params(core_scale=.75, satellite_scale=.25)
    full = generate_v441_signals(data, p)
    prefix = generate_v441_signals(data.iloc[:3002], p)
    pd.testing.assert_frame_equal(full.iloc[:3002], prefix)
    assert full.signal.abs().max() <= 3
    satellite = full.loc[full.v441_source.eq("satellite")]
    assert satellite.signal.max() <= .75
    # Every admitted tactical cycle originates from a fresh tactical entry.
    for _, cycle in satellite.groupby("cycle_id"):
        assert cycle.v441_event.iloc[0] in {"long_entry", "short_entry"}


def test_selection_lock_failure_preserves_all_existing_artifacts(tmp_path):
    import json
    import runpy
    from pathlib import Path
    save = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/research_v441.py"))["save_selection"]
    frozen = {"params": {"short_enabled": False}, "candidate_table_sha256": "original",
              "source_sha256": {}, "protocol_sha256": "protocol", "frozen_at_utc": "original_time"}
    (tmp_path / "final_selection_lock.json").write_text(json.dumps(frozen))
    names = ["phase2_candidates.csv", "phase2_candidates.json", "params.json"]
    for name in names:
        (tmp_path / name).write_text("original")
    with pytest.raises(RuntimeError, match="Selection lock differs"):
        save(tmp_path, "phase2_", {**frozen, "candidate_table_sha256": "changed"},
             "changed", "changed", tmp_path / "params.json")
    assert all((tmp_path / name).read_text() == "original" for name in names)
    assert json.loads((tmp_path / "final_selection_lock.json").read_text()) == frozen
    accepted = save(tmp_path, "phase2_", {**frozen, "frozen_at_utc": "new_time"},
                    "original", "original", tmp_path / "params.json")
    assert accepted["frozen_at_utc"] == "original_time"

import numpy as np
import pandas as pd
import pytest

from btc_regime.backtest import run_backtest
from btc_regime.micro_backtest import MicroBacktestConfig, maintenance_margin, run_micro_backtest
from btc_regime.strategy import StrategyParams, generate_signals


def synthetic_data(n=400):
    index = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 * np.exp(np.cumsum(np.full(n, 0.0002)))
    return pd.DataFrame({
        "open": close, "high": close * 1.005, "low": close * 0.995,
        "close": close, "volume": 1.0, "quote_volume": 100.0,
        "funding_rate": 0.0,
    }, index=index)


def test_signals_are_bounded_and_causal():
    data = synthetic_data()
    result = generate_signals(data, StrategyParams(max_leverage=3))
    assert result["signal"].abs().max() <= 3.0 + 1e-12
    assert result.index.equals(data.index)
    assert result["signal"].iloc[:100].eq(0).all() or result["signal"].iloc[:100].notna().all()


def test_backtest_compounds_and_charges_funding():
    data = synthetic_data(100)
    data["signal"] = 1.0
    data["funding_rate"] = 0.0001
    result = run_backtest(data)
    assert result.equity.iloc[-1] > 0
    assert result.metrics["trade_count"] >= 1
    assert result.metrics["max_leverage_observed"] <= 10
    assert result.metrics["rebalance_events"] >= result.metrics["trade_count"]


def test_leverage_hard_limit():
    with pytest.raises(ValueError):
        StrategyParams(max_leverage=10.01)
    result = generate_signals(synthetic_data(), StrategyParams(max_leverage=2, trend_scale=20))
    assert result["leverage"].max() <= 2.0 + 1e-12


def test_minute_engine_liquidates_on_mark_price_breach():
    signal_index = pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00", tz="UTC")])
    signaled = pd.DataFrame({"signal": [5.0]}, index=signal_index)
    minute_index = pd.DatetimeIndex([
        pd.Timestamp("2024-01-01 04:00", tz="UTC"),
        pd.Timestamp("2024-01-01 07:59", tz="UTC"),
    ])
    minute = pd.DataFrame({
        "trade_open": [100.0, 80.0], "trade_high": [101.0, 81.0],
        "trade_low": [75.0, 79.0], "trade_close": [80.0, 80.0],
        "trade_volume": [100_000.0, 100_000.0],
        "trade_quote_volume": [10_000_000.0, 10_000_000.0],
        "mark_open": [100.0, 80.0], "mark_high": [101.0, 81.0],
        "mark_low": [75.0, 79.0], "mark_close": [80.0, 80.0],
    }, index=minute_index)
    funding = pd.DataFrame({"funding_rate": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz="UTC"))
    result = run_micro_backtest(signaled, [minute], funding, MicroBacktestConfig())
    assert result.metrics["liquidation_count"] == 1
    assert result.equity.iloc[-1] == 0


def test_maintenance_margin_brackets_are_progressive():
    assert maintenance_margin(10_000)[0] == pytest.approx(40)
    assert maintenance_margin(100_000)[0] == pytest.approx(450)
    assert maintenance_margin(500_000)[0] == pytest.approx(3_700)


def test_volatility_risk_layer_deleverages_after_downside_shock():
    data = synthetic_data(500)
    data.loc[data.index[300], ["open", "high", "low", "close"]] *= 0.7
    data.loc[data.index[301]:, ["open", "high", "low", "close"]] *= 0.7
    params = StrategyParams(
        vol_risk_enabled=True,
        realized_vol_period=6,
        vol_baseline_period=30,
        vol_shock_enter=1.2,
        vol_shock_exit=1.05,
        vol_shock_scale=0.25,
        vol_momentum_period=3,
    )
    result = generate_signals(data, params)
    assert result["vol_risk_scale"].min() == pytest.approx(0.25)
    assert result.loc[data.index[300], "vol_momentum"] < 0


def test_volatility_parameters_are_validated():
    with pytest.raises(ValueError):
        StrategyParams(vol_shock_enter=1.0, vol_shock_exit=1.0)
    with pytest.raises(ValueError):
        StrategyParams(vol_shock_scale=1.01)


def test_volatility_risk_layer_does_not_use_future_prices():
    data = synthetic_data(500)
    params = StrategyParams(
        vol_risk_enabled=True,
        realized_vol_period=12,
        vol_baseline_period=90,
        vol_momentum_period=36,
    )
    original = generate_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[400]:, ["open", "high", "low", "close"]] *= 3
    modified = generate_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:400], modified["signal"].iloc[:400])
    pd.testing.assert_series_equal(
        original["vol_risk_scale"].iloc[:400], modified["vol_risk_scale"].iloc[:400]
    )


def test_momentum_and_funding_factors_reduce_crowded_trend_exposure():
    data = synthetic_data(500)
    data["funding_rate"] = 0.0005
    params = StrategyParams(
        momentum_factor_enabled=True,
        momentum_factor_period=6,
        momentum_factor_scale=0.25,
        funding_factor_enabled=True,
        funding_lookback=6,
        funding_high_threshold=0.0001,
        funding_factor_scale=0.5,
    )
    result = generate_signals(data, params)
    without_factor = generate_signals(data, StrategyParams())
    comparable = (without_factor["signal"] > 0) & (result["funding_ema"] > 0.0001)
    assert result["funding_ema"].iloc[-1] > 0.0001
    assert result["trend_momentum"].iloc[-1] > 0
    assert result["signal"].abs().max() <= params.max_leverage
    assert comparable.any()
    assert (result.loc[comparable, "signal"] < without_factor.loc[comparable, "signal"]).any()


def test_factor_diagnostics_do_not_use_future_funding_or_prices():
    data = synthetic_data(500)
    data["funding_rate"] = 0.0001
    params = StrategyParams(
        momentum_factor_enabled=True,
        funding_factor_enabled=True,
        funding_lookback=6,
    )
    original = generate_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[400]:, "funding_rate"] = 0.003
    changed.loc[changed.index[400]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_signals(changed, params)
    for column in ["signal", "trend_momentum", "funding_ema"]:
        pd.testing.assert_series_equal(original[column].iloc[:400], modified[column].iloc[:400])


def test_downside_allocation_boosts_calm_bars_and_respects_leverage_cap():
    data = synthetic_data(500)
    params = StrategyParams(
        max_leverage=2,
        trend_scale=10,
        downside_allocation_enabled=True,
        downside_vol_period=12,
        downside_calm_threshold=0.5,
        downside_stress_threshold=0.8,
        downside_calm_boost=1.5,
    )
    result = generate_signals(data, params)
    assert result["allocation_scale"].max() == pytest.approx(1.5)
    assert result["signal"].abs().max() <= 2.0 + 1e-12


def test_price_drawdown_brake_uses_hysteresis():
    data = synthetic_data(500)
    data.loc[data.index[300]:, ["open", "high", "low", "close"]] *= 0.7
    params = StrategyParams(
        drawdown_brake_enabled=True,
        price_drawdown_lookback=60,
        price_drawdown_enter=0.2,
        price_drawdown_exit=0.1,
        price_drawdown_scale=0.25,
    )
    result = generate_signals(data, params)
    assert result.loc[data.index[300], "price_drawdown"] < -0.2
    assert result.loc[data.index[300], "drawdown_risk_scale"] == pytest.approx(0.25)

import numpy as np
import pandas as pd

from btc_regime.range_grid import RangeGridParams, generate_range_grid_signals


def synthetic_market(close: np.ndarray) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=len(close), freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
            "quote_volume": 100_000.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def range_params() -> RangeGridParams:
    return RangeGridParams(
        range_adx_enter=80.0,
        range_adx_exit=90.0,
        chop_enter=45.0,
        chop_exit=20.0,
        efficiency_max=0.95,
        range_confirm_bars=1,
        range_exit_confirm_bars=1,
        channel_period=24,
        entry_percentile=0.30,
        entry_reversal_required=False,
        max_leverage=2.0,
    )


def test_range_grid_is_bounded_and_causal() -> None:
    close = 100 + 5 * np.sin(np.linspace(0, 40 * np.pi, 900))
    data = synthetic_market(close)
    original = generate_range_grid_signals(data, range_params())
    changed = data.copy()
    changed.loc[changed.index[500]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_range_grid_signals(changed, range_params())

    assert original.index.equals(data.index)
    assert original["signal"].abs().max() <= 2.0 + 1e-12
    assert original["rg_layers"].max() <= 3
    pd.testing.assert_series_equal(original["signal"].iloc[:500], modified["signal"].iloc[:500])
    assert (original["signal"].abs() > 0).any()


def test_range_grid_flattens_directional_trend() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.002)))
    result = generate_range_grid_signals(synthetic_market(close), range_params())
    assert not (result["signal"].abs() > 0).any()
    assert set(result["regime"].dropna().unique()) <= {"warmup", "trend_guard", "range_wait"}


def test_range_grid_requires_reversal_confirmation_when_enabled() -> None:
    close = 100 + 5 * np.sin(np.linspace(0, 40 * np.pi, 900))
    params = range_params()
    params = RangeGridParams(**{**params.to_dict(), "entry_reversal_required": True})
    result = generate_range_grid_signals(synthetic_market(close), params)
    entries = result.loc[result["rg_entry_event"]]
    assert not entries.empty
    long_entries = entries[entries["regime"] == "range_long"]
    short_entries = entries[entries["regime"] == "range_short"]
    assert (long_entries["close"] > long_entries["prev_close"]).all()
    assert (short_entries["close"] < short_entries["prev_close"]).all()

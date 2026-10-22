import pandas as pd
import pytest

from btc_regime.rebate_audit import combine_completed_equity
from btc_regime.v42 import V42CapitalParams


def test_settlement_is_not_booked_before_its_minute_completes():
    index = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    equity = pd.Series(100.0, index=index)
    neutral = pd.DataFrame({"neutral_return": [.1, .2]}, index=index[[0, 2]])
    result = combine_completed_equity(equity, neutral, V42CapitalParams(), equity * 0)
    assert result.neutral_sleeve_return.tolist() == pytest.approx([0, .1, 0, .2, 0])
    assert result.combined_equity.iloc[1] == pytest.approx(101.5)
    assert result.combined_equity.iloc[3] == pytest.approx(101.5 * 1.03)


def test_overlay_prefix_does_not_use_later_equity_or_settlements():
    index = pd.date_range("2024-01-01", periods=6, freq="h", tz="UTC")
    equity = pd.Series([100, 85, 75, 90, 110, 200], index=index)
    signal = pd.Series([0, 4, 0, 2, 0, 1], index=index)
    neutral = pd.DataFrame({"neutral_return": [.01, -.01, .5]}, index=index[[0, 2, 4]])
    full = combine_completed_equity(equity, neutral, V42CapitalParams(), signal)
    short = combine_completed_equity(equity.iloc[:4], neutral.iloc[:2], V42CapitalParams(), signal.iloc[:4])
    pd.testing.assert_frame_equal(short, full.iloc[:4])


def test_zero_neutral_returns_preserve_equity_and_timestamp():
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    equity = pd.Series([100, 110, 99, 120], index=index, dtype=float)
    neutral = pd.DataFrame({"neutral_return": [0.]}, index=index[:1])
    result = combine_completed_equity(equity, neutral, V42CapitalParams(), equity * 0)
    pd.testing.assert_series_equal(result.combined_equity, equity, check_names=False)

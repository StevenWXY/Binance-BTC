import numpy as np
import pandas as pd
import pytest

from btc_regime.v42 import V42CapitalParams, combine_direction_and_neutral, generate_neutral_sleeve


def test_v713_neutral_sleeve_uses_causal_settled_funding() -> None:
    index = pd.date_range("2024-01-01", periods=180, freq="8h", tz="UTC")
    funding = pd.DataFrame({"funding_rate": np.full(len(index), 0.0002)}, index=index)
    params = V42CapitalParams(minimum_30d_observations=30)
    original = generate_neutral_sleeve(funding, params)
    changed = funding.copy()
    changed.iloc[151:, 0] = -0.001
    modified = generate_neutral_sleeve(changed, params)
    pd.testing.assert_series_equal(original["active"].iloc[:151], modified["active"].iloc[:151])
    assert original["neutral_return"].iloc[151] != modified["neutral_return"].iloc[151]


def test_v713_neutral_overlay_adds_only_reserved_allocation() -> None:
    index = pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC")
    direction = pd.Series([100.0, 110.0, 110.0], index=index)
    neutral = pd.DataFrame(
        {"neutral_return": [0.10], "neutral_equity": [1.10]},
        index=pd.DatetimeIndex([index[1]]),
    )
    combined, _ = combine_direction_and_neutral(direction, neutral)
    assert combined["combined_return"].iloc[1] == pytest.approx(0.115)
    assert combined["combined_equity"].iloc[1] == pytest.approx(111.5)

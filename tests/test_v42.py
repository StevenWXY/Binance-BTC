import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from btc_regime.strategy import StrategyParams, generate_signals
from btc_regime.v42 import (
    V42CapitalParams,
    combine_direction_and_neutral,
    dynamic_neutral_allocation,
    generate_neutral_sleeve,
)


ROOT = Path(__file__).resolve().parents[1]


def funding_series(values: np.ndarray) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(values), freq="8h", tz="UTC")
    return pd.DataFrame({"funding_rate": values}, index=index)


def synthetic_market(n: int = 500) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 * np.exp(np.cumsum(np.full(n, 0.0002)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1.0,
            "quote_volume": 100.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_capital_allocations_are_validated() -> None:
    params = V42CapitalParams()
    assert params.direction_allocation + params.free_margin_allocation + params.neutral_allocation == 1
    assert params.transition_cost_rate == pytest.approx(0.000944)
    with pytest.raises(ValueError):
        V42CapitalParams(neutral_allocation=0.20)


def test_v42_direction_signal_is_exactly_three_quarters_of_v41() -> None:
    v41 = StrategyParams(
        **json.loads((ROOT / "configs/v4_refined_params.json").read_text(encoding="utf-8"))
    )
    v42 = StrategyParams(
        **json.loads((ROOT / "configs/v4_2_params.json").read_text(encoding="utf-8"))
    )
    market = synthetic_market()
    expected = generate_signals(market, v41)["signal"] * 0.75
    actual = generate_signals(market, v42)["signal"]
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_neutral_state_is_causal_at_current_settlement() -> None:
    values = np.full(180, 0.0002)
    params = V42CapitalParams(minimum_30d_observations=30)
    original = generate_neutral_sleeve(funding_series(values), params)
    changed_values = values.copy()
    changed_values[150:] = -0.001
    modified = generate_neutral_sleeve(funding_series(changed_values), params)
    pd.testing.assert_series_equal(original["active"].iloc[:151], modified["active"].iloc[:151])
    assert original["neutral_return"].iloc[150] != modified["neutral_return"].iloc[150]


def test_neutral_sleeve_enters_and_exits_with_hysteresis() -> None:
    values = np.concatenate([np.full(120, 0.0002), np.full(12, -0.0002)])
    params = V42CapitalParams(minimum_30d_observations=30)
    result = generate_neutral_sleeve(funding_series(values), params)
    assert result["active"].any()
    assert not result["active"].iloc[-1]
    assert (result["reason"] == "enter_arbitrage").any()
    assert result["reason"].isin(["exit_negative_streak", "exit_rate_filter"]).any()


def test_combined_return_adds_only_neutral_allocation() -> None:
    index = pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC")
    direction = pd.Series([100.0, 110.0, 110.0], index=index)
    neutral = pd.DataFrame(
        {"neutral_return": [0.10], "neutral_equity": [1.10]},
        index=pd.DatetimeIndex([index[1]]),
    )
    combined, _ = combine_direction_and_neutral(direction, neutral)
    assert combined["combined_return"].iloc[1] == pytest.approx(0.115)
    assert combined["combined_equity"].iloc[1] == pytest.approx(111.5)


def test_neutral_capital_is_recalled_and_redeployed_with_hysteresis() -> None:
    index = pd.date_range("2024-01-01", periods=7, freq="4h", tz="UTC")
    equity = pd.Series([100, 84, 83, 79, 85, 91, 92], index=index, dtype=float)
    allocation = dynamic_neutral_allocation(equity, None)
    assert allocation["neutral_allocation"].iloc[1] == pytest.approx(0.075)
    assert allocation["neutral_allocation"].iloc[3] == 0
    assert allocation["neutral_allocation"].iloc[4] == 0
    assert allocation["neutral_allocation"].iloc[5] == pytest.approx(0.15)


def test_margin_recall_restores_free_margin_target() -> None:
    index = pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC")
    equity = pd.Series([100.0, 100.0], index=index)
    exposure = pd.Series([5.2, 5.2], index=index)
    allocation = dynamic_neutral_allocation(equity, exposure)
    assert allocation["recall_state"].eq("margin_recall").all()
    assert allocation["neutral_allocation"].iloc[0] == pytest.approx(0.08)
    assert allocation["estimated_free_margin"].iloc[0] == pytest.approx(0.12)

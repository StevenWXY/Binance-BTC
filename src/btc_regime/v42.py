"""Capital overlay and causal neutral sleeve for V4.2."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .backtest import calculate_metrics


@dataclass(frozen=True)
class V42CapitalParams:
    direction_allocation: float = 0.75
    free_margin_allocation: float = 0.10
    neutral_allocation: float = 0.15
    exchange_leverage: float = 6.5
    idle_apy: float = 0.04
    arb_notional_fraction: float = 0.80
    entry_7d_annualized: float = 0.12
    entry_30d_annualized: float = 0.06
    exit_7d_annualized: float = 0.03
    entry_positive_ratio: float = 0.70
    exit_positive_ratio: float = 0.55
    negative_settlements_exit: int = 2
    minimum_30d_observations: int = 60
    spot_fee_bps: float = 7.0
    futures_fee_bps: float = 2.8
    slippage_per_leg_bps: float = 1.0
    recall_trigger_free_margin: float = 0.08
    recall_restore_free_margin: float = 0.12
    half_recall_drawdown: float = 0.15
    full_recall_drawdown: float = 0.20
    redeploy_drawdown: float = 0.10

    def __post_init__(self) -> None:
        allocations = (
            self.direction_allocation,
            self.free_margin_allocation,
            self.neutral_allocation,
        )
        if any(value < 0 or value > 1 for value in allocations):
            raise ValueError("capital allocations must be between zero and one")
        if not np.isclose(sum(allocations), 1.0):
            raise ValueError("capital allocations must sum to one")
        if self.exchange_leverage <= 0:
            raise ValueError("exchange_leverage must be positive")
        if not 0 <= self.arb_notional_fraction <= 1:
            raise ValueError("arb_notional_fraction must be between zero and one")
        if not self.entry_7d_annualized > self.exit_7d_annualized:
            raise ValueError("entry threshold must exceed exit threshold")
        if not self.entry_positive_ratio > self.exit_positive_ratio:
            raise ValueError("entry positive ratio must exceed exit positive ratio")
        if self.negative_settlements_exit < 1:
            raise ValueError("negative_settlements_exit must be positive")
        if self.minimum_30d_observations < 1:
            raise ValueError("minimum_30d_observations must be positive")
        if not 0 <= self.recall_trigger_free_margin < self.recall_restore_free_margin:
            raise ValueError("recall thresholds must be ordered and non-negative")
        if not 0 <= self.redeploy_drawdown < self.half_recall_drawdown < self.full_recall_drawdown < 1:
            raise ValueError("drawdown recall thresholds must be strictly ordered")

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)

    @property
    def transition_cost_rate(self) -> float:
        per_notional_bps = (
            self.spot_fee_bps
            + self.futures_fee_bps
            + 2 * self.slippage_per_leg_bps
        )
        return self.arb_notional_fraction * per_notional_bps / 10_000


def _funding_series(funding: pd.DataFrame | pd.Series) -> pd.Series:
    if isinstance(funding, pd.DataFrame):
        if "funding_rate" not in funding:
            raise ValueError("funding data must contain funding_rate")
        rate = funding["funding_rate"].copy()
    else:
        rate = funding.copy()
    if rate.empty:
        raise ValueError("funding data is empty")
    index = pd.to_datetime(rate.index, utc=True, format="mixed")
    rate.index = index
    return pd.to_numeric(rate, errors="coerce").dropna().sort_index()


def generate_neutral_sleeve(
    funding: pd.DataFrame | pd.Series,
    params: V42CapitalParams = V42CapitalParams(),
) -> pd.DataFrame:
    """Generate causal funding-arbitrage returns for the neutral sleeve.

    The state applied at each settlement uses only rates settled before that
    timestamp. Returns exclude spot-perpetual basis PnL and should therefore be
    treated as an execution proxy, not a complete arbitrage backtest.
    """
    rate = _funding_series(funding)
    settled = rate.shift(1)
    trailing_7d = settled.rolling("7D").sum() * 365.25 / 7
    trailing_30d = settled.rolling("30D").sum() * 365.25 / 30
    positive_observation = settled.where(settled.isna(), (settled > 0).astype(float))
    positive_ratio_7d = positive_observation.rolling("7D").mean()
    observation_count_30d = settled.rolling("30D").count()

    elapsed_hours = rate.index.to_series().diff().dt.total_seconds().div(3600)
    elapsed_hours = elapsed_hours.fillna(0.0).clip(lower=0.0, upper=24.0)

    active = False
    negative_streak = 0
    rows: list[dict[str, object]] = []
    for timestamp, funding_rate in rate.items():
        ready = observation_count_30d.loc[timestamp] >= params.minimum_30d_observations
        enter = (
            ready
            and trailing_7d.loc[timestamp] >= params.entry_7d_annualized
            and trailing_30d.loc[timestamp] >= params.entry_30d_annualized
            and positive_ratio_7d.loc[timestamp] >= params.entry_positive_ratio
        )
        exit_for_rate = (
            trailing_7d.loc[timestamp] <= params.exit_7d_annualized
            or positive_ratio_7d.loc[timestamp] < params.exit_positive_ratio
        )
        exit_for_negatives = negative_streak >= params.negative_settlements_exit

        previous_active = active
        reason = "hold_arbitrage" if active else "hold_idle"
        if not active and enter:
            active = True
            reason = "enter_arbitrage"
        elif active and (exit_for_rate or exit_for_negatives):
            active = False
            reason = "exit_negative_streak" if exit_for_negatives else "exit_rate_filter"

        state_changed = active != previous_active
        transition_cost = params.transition_cost_rate if state_changed else 0.0
        funding_return = params.arb_notional_fraction * float(funding_rate) if active else 0.0
        idle_return = 0.0
        if not active and elapsed_hours.loc[timestamp] > 0:
            idle_return = (
                (1 + params.idle_apy)
                ** (float(elapsed_hours.loc[timestamp]) / (365.25 * 24))
                - 1
            )
        neutral_return = funding_return + idle_return - transition_cost
        rows.append(
            {
                "timestamp": timestamp,
                "funding_rate": float(funding_rate),
                "trailing_7d_annualized": float(trailing_7d.loc[timestamp]),
                "trailing_30d_annualized": float(trailing_30d.loc[timestamp]),
                "positive_ratio_7d": float(positive_ratio_7d.loc[timestamp]),
                "observation_count_30d": int(observation_count_30d.loc[timestamp]),
                "active": active,
                "state_changed": state_changed,
                "reason": reason,
                "funding_return": funding_return,
                "idle_return": idle_return,
                "transition_cost_return": transition_cost,
                "neutral_return": neutral_return,
            }
        )
        negative_streak = negative_streak + 1 if funding_rate < 0 else 0

    result = pd.DataFrame.from_records(rows).set_index("timestamp")
    result["neutral_equity"] = (1 + result["neutral_return"]).cumprod()
    result["drawdown"] = result["neutral_equity"] / result["neutral_equity"].cummax() - 1
    return result


def neutral_metrics(neutral: pd.DataFrame) -> dict[str, float]:
    equity = neutral["neutral_equity"]
    returns = neutral["neutral_return"]
    years = max(
        (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400),
        1 / 365.25,
    )
    standard_deviation = returns.std(ddof=1)
    median_seconds = equity.index.to_series().diff().dt.total_seconds().median()
    periods_per_year = 365.25 * 86400 / median_seconds
    downside_deviation = returns.where(returns < 0, 0).std(ddof=1)
    return {
        "final_multiple": float(equity.iloc[-1]),
        "total_return": float(equity.iloc[-1] - 1),
        "cagr": float(equity.iloc[-1] ** (1 / years) - 1),
        "annualized_volatility": float(standard_deviation * np.sqrt(periods_per_year)),
        "sharpe": float(returns.mean() / standard_deviation * np.sqrt(periods_per_year)),
        "sortino": float(
            returns.mean() / downside_deviation * np.sqrt(periods_per_year)
            if downside_deviation > 0
            else 0.0
        ),
        "max_drawdown": float(neutral["drawdown"].min()),
        "active_fraction": float(neutral["active"].mean()),
        "state_change_count": float(neutral["state_changed"].sum()),
    }


def combine_direction_and_neutral(
    direction_equity: pd.Series,
    neutral: pd.DataFrame,
    params: V42CapitalParams = V42CapitalParams(),
    direction_signal: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Overlay neutral-sleeve returns on the 4h direction equity curve."""
    direction = direction_equity.sort_index().astype(float)
    direction_return = direction.pct_change().fillna(0.0)
    neutral_4h = (
        neutral["neutral_return"]
        .groupby(neutral.index.floor("4h"))
        .apply(lambda values: float((1 + values).prod() - 1))
    )
    neutral_4h = neutral_4h.reindex(direction.index, fill_value=0.0)
    allocation = dynamic_neutral_allocation(direction, direction_signal, params)
    # Allocation decided at the prior boundary earns the return ending now.
    applied_allocation = allocation["neutral_allocation"].shift(1).fillna(
        params.neutral_allocation
    )
    combined_return = direction_return + applied_allocation * neutral_4h
    combined_return.iloc[0] = 0.0
    combined_equity = direction.iloc[0] * (1 + combined_return).cumprod()
    frame = pd.DataFrame(
        {
            "direction_equity": direction,
            "direction_return": direction_return,
            "neutral_sleeve_return": neutral_4h,
            "neutral_allocation": applied_allocation,
            "neutral_allocation_next": allocation["neutral_allocation"],
            "neutral_recall_state": allocation["recall_state"],
            "estimated_free_margin_next": allocation["estimated_free_margin"],
            "neutral_portfolio_contribution": applied_allocation * neutral_4h,
            "combined_return": combined_return,
            "combined_equity": combined_equity,
        }
    )
    frame["combined_drawdown"] = (
        frame["combined_equity"] / frame["combined_equity"].cummax() - 1
    )
    metrics = calculate_metrics(
        frame["combined_equity"],
        frame["combined_return"].iloc[1:],
        pd.DataFrame(),
        2190,
    )
    return frame, metrics


def dynamic_neutral_allocation(
    direction_equity: pd.Series,
    direction_signal: pd.Series | None,
    params: V42CapitalParams = V42CapitalParams(),
) -> pd.DataFrame:
    """Return the causal neutral allocation available for the next period."""
    equity = direction_equity.sort_index().astype(float)
    drawdown = equity / equity.cummax() - 1
    if direction_signal is None:
        signal = pd.Series(0.0, index=equity.index)
    else:
        signal = direction_signal.sort_index().reindex(equity.index).ffill().fillna(0.0)

    drawdown_state = "normal"
    rows: list[dict[str, object]] = []
    for timestamp in equity.index:
        current_drawdown = float(drawdown.loc[timestamp])
        if drawdown_state == "normal":
            if current_drawdown <= -params.full_recall_drawdown:
                drawdown_state = "full_recall"
            elif current_drawdown <= -params.half_recall_drawdown:
                drawdown_state = "half_recall"
        elif drawdown_state == "half_recall":
            if current_drawdown <= -params.full_recall_drawdown:
                drawdown_state = "full_recall"
            elif current_drawdown >= -params.redeploy_drawdown:
                drawdown_state = "normal"
        elif current_drawdown >= -params.redeploy_drawdown:
            drawdown_state = "normal"

        drawdown_cap = {
            "normal": params.neutral_allocation,
            "half_recall": params.neutral_allocation / 2,
            "full_recall": 0.0,
        }[drawdown_state]
        required_initial_margin = abs(float(signal.loc[timestamp])) / params.exchange_leverage
        free_before_recall = 1 - params.neutral_allocation - required_initial_margin
        margin_cap = params.neutral_allocation
        margin_recall = free_before_recall < params.recall_trigger_free_margin
        if margin_recall:
            margin_cap = max(
                0.0,
                1 - required_initial_margin - params.recall_restore_free_margin,
            )
        neutral_allocation = min(drawdown_cap, margin_cap)
        estimated_free_margin = 1 - neutral_allocation - required_initial_margin
        recall_state = drawdown_state
        if margin_recall and neutral_allocation < drawdown_cap:
            recall_state = "margin_recall"
        rows.append(
            {
                "timestamp": timestamp,
                "direction_drawdown": current_drawdown,
                "direction_signal": float(signal.loc[timestamp]),
                "required_initial_margin": required_initial_margin,
                "neutral_allocation": neutral_allocation,
                "estimated_free_margin": estimated_free_margin,
                "recall_state": recall_state,
            }
        )
    return pd.DataFrame.from_records(rows).set_index("timestamp")


def annual_return_table(
    returns: pd.Series,
    *,
    active: pd.Series | None = None,
    state_changed: pd.Series | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for year, period_returns in returns.groupby(returns.index.year):
        equity = (1 + period_returns).cumprod()
        drawdown = equity / equity.cummax() - 1
        elapsed_days = max(
            (period_returns.index[-1] - period_returns.index[0]).total_seconds() / 86400,
            1.0,
        )
        row: dict[str, float | int] = {
            "year": int(year),
            "period_return": float(equity.iloc[-1] - 1),
            "annualized_return": float(equity.iloc[-1] ** (365.25 / elapsed_days) - 1),
            "max_drawdown": float(drawdown.min()),
        }
        if active is not None:
            row["active_fraction"] = float(active.reindex(period_returns.index).mean())
        if state_changed is not None:
            row["state_change_count"] = int(
                state_changed.reindex(period_returns.index, fill_value=False).sum()
            )
        rows.append(row)
    return pd.DataFrame(rows)

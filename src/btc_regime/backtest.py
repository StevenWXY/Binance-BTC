"""Event-ordered backtest for a single linear USD-M perpetual contract."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_bps: float = 4.0
    slippage_bps: float = 1.0
    funding_enabled: bool = True
    periods_per_year: int = 2190


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    trades: pd.DataFrame
    metrics: dict[str, float]


def calculate_metrics(
    equity: pd.Series,
    returns: pd.Series,
    trades: pd.DataFrame,
    periods_per_year: int,
) -> dict[str, float]:
    if equity.empty:
        return {}
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    years = max((equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if equity.iloc[-1] > 0 else -1.0
    volatility = returns.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year) if returns.std(ddof=1) > 0 else 0.0
    downside = returns.where(returns < 0, 0).std(ddof=1) * np.sqrt(periods_per_year)
    sortino = returns.mean() / returns.where(returns < 0, 0).std(ddof=1) * np.sqrt(periods_per_year) if downside > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    win_rate = float((trades["pnl"] > 0).mean()) if len(trades) else 0.0
    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "annualized_volatility": float(volatility),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": float(drawdown.min()),
        "trade_count": float(len(trades)),
        "win_rate": win_rate,
        "final_equity": float(equity.iloc[-1]),
    }


def run_backtest(data: pd.DataFrame, config: BacktestConfig = BacktestConfig()) -> BacktestResult:
    required = {"open", "high", "low", "close", "signal"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    frame = data.sort_index().copy()
    funding = frame.get("funding_rate", pd.Series(0.0, index=frame.index)).fillna(0.0)
    cost_rate = (config.fee_bps + config.slippage_bps) / 10_000
    equity = config.initial_cash
    previous_position = 0.0
    equity_values = [equity]
    return_values = [0.0]
    timestamps = [frame.index[0]]
    records: list[dict[str, object]] = []
    open_trade: dict[str, object] | None = None
    signals = frame["signal"].fillna(0.0).clip(-10, 10)

    for i in range(len(frame) - 1):
        timestamp = frame.index[i]
        next_timestamp = frame.index[i + 1]
        target = float(signals.iloc[i])
        turnover = abs(target - previous_position)
        fee = equity * turnover * cost_rate
        equity -= fee
        previous_side = np.sign(previous_position)
        target_side = np.sign(target)
        side_changed = previous_side != target_side
        if side_changed:
            if open_trade is not None:
                records.append({
                    "entry_time": open_trade["entry_time"],
                    "exit_time": timestamp,
                    "side": open_trade["side"],
                    "entry_price": open_trade["entry_price"],
                    "exit_price": float(frame["close"].iloc[i]),
                    "bars": i - int(open_trade["entry_index"]),
                    "pnl": equity - float(open_trade["equity_before"]),
                })
                open_trade = None
            if abs(target) > 1e-8:
                open_trade = {
                    "entry_time": timestamp,
                    "entry_index": i,
                    "entry_price": float(frame["close"].iloc[i]),
                    "side": "long" if target > 0 else "short",
                    "equity_before": equity,
                }

        price_return = float(frame["close"].iloc[i + 1] / frame["close"].iloc[i] - 1)
        funding_return = -target * float(funding.iloc[i + 1]) if config.funding_enabled else 0.0
        period_return = target * price_return + funding_return
        period_return = max(period_return, -0.999)
        equity *= 1 + period_return
        if equity <= 0:
            equity = 0.01
            target = 0.0
        equity_values.append(equity)
        return_values.append(equity_values[-1] / equity_values[-2] - 1)
        timestamps.append(next_timestamp)
        previous_position = target

    if open_trade is not None:
        records.append({
            "entry_time": open_trade["entry_time"], "exit_time": frame.index[-1],
            "side": open_trade["side"], "entry_price": open_trade["entry_price"],
            "exit_price": float(frame["close"].iloc[-1]),
            "bars": len(frame) - 1 - int(open_trade["entry_index"]),
            "pnl": equity - float(open_trade["equity_before"]),
        })
    equity_series = pd.Series(equity_values, index=pd.DatetimeIndex(timestamps), name="equity")
    returns = pd.Series(return_values, index=equity_series.index, name="return")
    trades = pd.DataFrame.from_records(records)
    metrics = calculate_metrics(equity_series, returns.iloc[1:], trades, config.periods_per_year)
    clipped_signal = signals.astype(float)
    signal_delta = clipped_signal.diff().abs().fillna(clipped_signal.abs())
    metrics.update({
        "max_leverage_observed": float(clipped_signal.abs().max()),
        "average_leverage": float(clipped_signal.abs().mean()),
        "turnover_multiple": float(signal_delta.sum()),
        "rebalance_events": float((signal_delta > 1e-8).sum()),
    })
    return BacktestResult(equity=equity_series, returns=returns, trades=trades, metrics=metrics)

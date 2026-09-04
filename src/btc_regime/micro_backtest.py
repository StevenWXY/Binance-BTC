"""Minute-level USD-M execution, margin, and liquidation simulation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .backtest import BacktestResult, calculate_metrics
from .strategy import StrategyParams


# BTCUSDT bracket assumptions. Binance does not publish historical bracket snapshots
# in the market-data archive, so every report records these values explicitly.
MAINTENANCE_BRACKETS = (
    (50_000.0, 0.004, 0.0),
    (250_000.0, 0.005, 50.0),
    (1_000_000.0, 0.010, 1_300.0),
    (10_000_000.0, 0.025, 16_300.0),
    (20_000_000.0, 0.050, 266_300.0),
    (50_000_000.0, 0.100, 1_266_300.0),
    (100_000_000.0, 0.125, 2_516_300.0),
    (200_000_000.0, 0.150, 5_016_300.0),
    (300_000_000.0, 0.250, 25_016_300.0),
    (500_000_000.0, 0.500, 100_016_300.0),
    (float("inf"), 1.000, 350_016_300.0),
)


@dataclass(frozen=True)
class MicroBacktestConfig:
    initial_cash: float = 10_000.0
    taker_fee_bps: float = 4.0
    base_slippage_bps: float = 1.0
    impact_bps: float = 8.0
    max_minute_participation: float = 0.02
    liquidation_fee_bps: float = 50.0
    liquidation_slippage_bps: float = 5.0
    quantity_step: float = 0.001
    min_notional: float = 5.0
    periods_per_year: int = 2190
    strategy_drawdown_enabled: bool = False
    strategy_drawdown_level_1: float = 0.10
    strategy_drawdown_scale_1: float = 0.80
    strategy_drawdown_level_2: float = 0.15
    strategy_drawdown_scale_2: float = 0.50
    strategy_drawdown_level_3: float = 0.20
    strategy_drawdown_scale_3: float = 0.25


@dataclass
class MicroBacktestResult:
    equity: pd.Series
    returns: pd.Series
    fills: pd.DataFrame
    trades: pd.DataFrame
    liquidations: pd.DataFrame
    funding: pd.DataFrame
    metrics: dict[str, float]


@dataclass
class _Account:
    wallet: float
    quantity: float = 0.0
    entry_price: float = 0.0
    fees_paid: float = 0.0
    funding_paid: float = 0.0
    realized_pnl: float = 0.0

    def unrealized(self, mark_price: float) -> float:
        return self.quantity * (mark_price - self.entry_price)

    def equity(self, mark_price: float) -> float:
        return self.wallet + self.unrealized(mark_price)

    def fill(self, delta: float, price: float, fee_rate: float) -> tuple[float, float]:
        old_quantity = self.quantity
        new_quantity = old_quantity + delta
        realized = 0.0
        if abs(old_quantity) < 1e-12:
            self.entry_price = price if abs(new_quantity) > 1e-12 else 0.0
        elif old_quantity * delta > 0:
            self.entry_price = (
                abs(old_quantity) * self.entry_price + abs(delta) * price
            ) / abs(new_quantity)
        elif old_quantity * delta < 0:
            closing_quantity = min(abs(delta), abs(old_quantity))
            realized = closing_quantity * (price - self.entry_price) * np.sign(old_quantity)
            self.wallet += realized
            self.realized_pnl += realized
            if abs(new_quantity) < 1e-12:
                self.entry_price = 0.0
            elif np.sign(new_quantity) != np.sign(old_quantity):
                self.entry_price = price
        fee = abs(delta) * price * fee_rate
        self.wallet -= fee
        self.fees_paid += fee
        self.quantity = 0.0 if abs(new_quantity) < 1e-12 else new_quantity
        return realized, fee


def maintenance_margin(notional: float) -> tuple[float, float, float]:
    """Return maintenance amount, rate, and cumulative deduction."""
    for cap, rate, cumulative in MAINTENANCE_BRACKETS:
        if notional <= cap:
            return max(notional * rate - cumulative, 0.0), rate, cumulative
    raise AssertionError("unreachable maintenance bracket")


def _round_toward_zero(value: float, step: float) -> float:
    return math.copysign(math.floor(abs(value) / step + 1e-12) * step, value)


def _liquidation_price(account: _Account, adverse_price: float) -> float:
    quantity = account.quantity
    absolute_quantity = abs(quantity)
    if absolute_quantity < 1e-12:
        return adverse_price
    _, rate, cumulative = maintenance_margin(absolute_quantity * adverse_price)
    if quantity > 0:
        numerator = absolute_quantity * account.entry_price - account.wallet - cumulative
        return max(numerator / (absolute_quantity * (1 - rate)), 0.0)
    numerator = account.wallet + absolute_quantity * account.entry_price + cumulative
    return max(numerator / (absolute_quantity * (1 + rate)), 0.0)


def _signal_events(signaled: pd.DataFrame) -> dict[pd.Timestamp, float]:
    signal = signaled["signal"].fillna(0.0).clip(-10, 10)
    changed = signal.ne(signal.shift(1)).fillna(True)
    # Kline indices are opens; their completed-close signal can trade at the next 4h boundary.
    return {(timestamp + pd.Timedelta(hours=4)): float(value) for timestamp, value in signal[changed].items()}


def _protection_events(
    signaled: pd.DataFrame,
) -> dict[pd.Timestamp, tuple[float, float]]:
    """Return causal stop/take-profit levels when supplied by a strategy."""
    required = {"stop_price", "take_profit_price"}
    if not required.issubset(signaled.columns):
        return {}
    levels: dict[pd.Timestamp, tuple[float, float]] = {}
    for timestamp, row in signaled.iterrows():
        stop = float(row["stop_price"]) if pd.notna(row["stop_price"]) else np.nan
        take = float(row["take_profit_price"]) if pd.notna(row["take_profit_price"]) else np.nan
        levels[timestamp + pd.Timedelta(hours=4)] = (stop, take)
    return levels


def run_micro_backtest(
    signaled: pd.DataFrame,
    minute_batches: Iterable[pd.DataFrame],
    funding: pd.DataFrame,
    config: MicroBacktestConfig = MicroBacktestConfig(),
) -> MicroBacktestResult:
    events = _signal_events(signaled)
    protection_events = _protection_events(signaled)
    funding_events = funding["funding_rate"].groupby(funding.index.floor("1min")).sum().to_dict()
    account = _Account(wallet=config.initial_cash)
    pending_signal: float | None = None
    active_protection: tuple[float, float] | None = None
    fills: list[dict[str, object]] = []
    liquidations: list[dict[str, object]] = []
    funding_records: list[dict[str, object]] = []
    trade_cycles: list[dict[str, object]] = []
    cycle: dict[str, object] | None = None
    equity_times: list[pd.Timestamp] = []
    equity_values: list[float] = []
    max_leverage = max_margin_ratio = max_participation = 0.0
    min_margin_buffer = float("inf")
    order_notional = 0.0
    last_row: object | None = None
    last_timestamp: pd.Timestamp | None = None
    peak_equity = config.initial_cash

    fee_rate = config.taker_fee_bps / 10_000
    liquidation_fee_rate = config.liquidation_fee_bps / 10_000

    def execute_liquidation(timestamp: pd.Timestamp, adverse_price: float, maintenance: float) -> None:
        nonlocal cycle, pending_signal, active_protection
        trigger_price = _liquidation_price(account, adverse_price)
        close_delta = -account.quantity
        execution_price = trigger_price * (
            1 - math.copysign(config.liquidation_slippage_bps / 10_000, account.quantity)
        )
        quantity = abs(account.quantity)
        equity_before = account.equity(trigger_price)
        realized, fee = account.fill(close_delta, execution_price, liquidation_fee_rate)
        account.wallet = max(account.wallet, 0.0)
        fills.append({
            "timestamp": timestamp,
            "reason": "liquidation",
            "side": "sell" if close_delta < 0 else "buy",
            "quantity": quantity,
            "price": execution_price,
            "notional": quantity * execution_price,
            "fee": fee,
            "slippage_bps": config.liquidation_slippage_bps,
            "participation": np.nan,
            "realized_pnl": realized,
            "position_after": 0.0,
        })
        liquidations.append({
            "timestamp": timestamp,
            "mark_extreme": adverse_price,
            "trigger_price": trigger_price,
            "execution_price": execution_price,
            "quantity": quantity,
            "equity_at_trigger": equity_before,
            "maintenance_margin": maintenance,
            "wallet_after": account.wallet,
        })
        if cycle is not None:
            trade_cycles.append({
                **cycle,
                "exit_time": timestamp,
                "pnl": account.wallet - float(cycle["equity_before"]),
                "exit_reason": "liquidation",
            })
            cycle = None
        pending_signal = None
        active_protection = None

    def execute_protective_exit(
        timestamp: pd.Timestamp,
        trigger_price: float,
        reason: str,
    ) -> None:
        nonlocal cycle, pending_signal, active_protection
        if abs(account.quantity) < 1e-12:
            return
        close_delta = -account.quantity
        execution_price = trigger_price * (
            1 - math.copysign(config.base_slippage_bps / 10_000, account.quantity)
        )
        quantity = abs(account.quantity)
        equity_before = account.equity(trigger_price)
        realized, fee = account.fill(close_delta, execution_price, fee_rate)
        fills.append({
            "timestamp": timestamp,
            "reason": reason,
            "side": "sell" if close_delta < 0 else "buy",
            "quantity": quantity,
            "price": execution_price,
            "trigger_price": trigger_price,
            "notional": quantity * execution_price,
            "fee": fee,
            "slippage_bps": config.base_slippage_bps,
            "participation": np.nan,
            "realized_pnl": realized,
            "position_after": 0.0,
        })
        if cycle is not None:
            trade_cycles.append({
                **cycle,
                "exit_time": timestamp,
                "pnl": account.wallet - float(cycle["equity_before"]),
                "exit_reason": reason,
                "equity_at_trigger": equity_before,
            })
            cycle = None
        pending_signal = None
        active_protection = None

    for batch in minute_batches:
        for row in batch.itertuples():
            timestamp = row.Index
            last_row = row
            last_timestamp = timestamp
            mark_open = float(row.mark_open)
            if timestamp in protection_events:
                active_protection = protection_events[timestamp]
            if not equity_times:
                equity_times.append(timestamp)
                equity_values.append(max(account.equity(mark_open), 0.0))
            peak_equity = max(peak_equity, max(account.equity(mark_open), 0.0))

            # Existing positions are checked at the minute open before funding or orders.
            if abs(account.quantity) > 1e-12:
                open_equity = account.equity(mark_open)
                open_maintenance, _, _ = maintenance_margin(abs(account.quantity) * mark_open)
                if open_equity <= open_maintenance:
                    execute_liquidation(timestamp, mark_open, open_maintenance)

            rate = float(funding_events.get(timestamp, 0.0))
            if rate and abs(account.quantity) > 1e-12:
                payment = account.quantity * mark_open * rate
                account.wallet -= payment
                account.funding_paid += payment
                funding_records.append({
                    "timestamp": timestamp,
                    "rate": rate,
                    "mark_price": mark_open,
                    "position": account.quantity,
                    "notional": abs(account.quantity) * mark_open,
                    "payment": payment,
                    "wallet_after": account.wallet,
                })

            if timestamp in events:
                pending_signal = events[timestamp]

            if pending_signal is not None and account.wallet > 0:
                pre_fill_equity = max(account.equity(mark_open), 0.0)
                effective_signal = pending_signal
                if config.strategy_drawdown_enabled and peak_equity > 0:
                    current_drawdown = max(0.0, 1.0 - pre_fill_equity / peak_equity)
                    if current_drawdown >= config.strategy_drawdown_level_3:
                        effective_signal *= config.strategy_drawdown_scale_3
                    elif current_drawdown >= config.strategy_drawdown_level_2:
                        effective_signal *= config.strategy_drawdown_scale_2
                    elif current_drawdown >= config.strategy_drawdown_level_1:
                        effective_signal *= config.strategy_drawdown_scale_1
                target_quantity = _round_toward_zero(
                    effective_signal * pre_fill_equity / float(row.trade_open), config.quantity_step
                )
                desired_delta = target_quantity - account.quantity
                desired_notional = abs(desired_delta) * float(row.trade_open)
                if desired_notional < config.min_notional:
                    pending_signal = None
                else:
                    available_quote = max(float(row.trade_quote_volume), 0.0)
                    capacity_quantity = (
                        available_quote * config.max_minute_participation / float(row.trade_open)
                    )
                    fill_quantity = min(abs(desired_delta), capacity_quantity)
                    fill_quantity = abs(_round_toward_zero(fill_quantity, config.quantity_step))
                    if fill_quantity >= config.quantity_step:
                        delta = math.copysign(fill_quantity, desired_delta)
                        fill_notional = fill_quantity * float(row.trade_open)
                        participation = fill_notional / max(available_quote, fill_notional)
                        slippage_bps = config.base_slippage_bps + config.impact_bps * math.sqrt(participation)
                        execution_price = float(row.trade_open) * (
                            1 + math.copysign(slippage_bps / 10_000, delta)
                        )
                        old_side = np.sign(account.quantity)
                        old_equity = account.equity(mark_open)
                        realized, fee = account.fill(delta, execution_price, fee_rate)
                        new_side = np.sign(account.quantity)
                        order_notional += abs(delta) * execution_price
                        max_participation = max(max_participation, participation)
                        fills.append({
                            "timestamp": timestamp,
                            "reason": "signal",
                            "side": "buy" if delta > 0 else "sell",
                            "quantity": abs(delta),
                            "price": execution_price,
                            "notional": abs(delta) * execution_price,
                            "fee": fee,
                            "slippage_bps": slippage_bps,
                            "participation": participation,
                            "realized_pnl": realized,
                            "position_after": account.quantity,
                        })
                        if old_side == 0 and new_side != 0:
                            cycle = {
                                "entry_time": timestamp,
                                "side": "long" if new_side > 0 else "short",
                                "equity_before": old_equity,
                            }
                        elif old_side != 0 and new_side != old_side:
                            if cycle is not None:
                                trade_cycles.append({
                                    **cycle,
                                    "exit_time": timestamp,
                                    "pnl": account.equity(mark_open) - float(cycle["equity_before"]),
                                    "exit_reason": "signal",
                                })
                            cycle = None if new_side == 0 else {
                                "entry_time": timestamp,
                                "side": "long" if new_side > 0 else "short",
                                "equity_before": account.equity(mark_open),
                            }
                        remaining = target_quantity - account.quantity
                        if abs(remaining) * execution_price < config.min_notional:
                            pending_signal = None

            if abs(account.quantity) > 1e-12 and active_protection is not None:
                stop, take = active_protection
                trigger_price = np.nan
                reason = ""
                if account.quantity > 0:
                    if np.isfinite(stop) and float(row.mark_low) <= stop:
                        trigger_price, reason = stop, "stop_loss"
                    elif np.isfinite(take) and float(row.mark_high) >= take:
                        trigger_price, reason = take, "take_profit"
                else:
                    if np.isfinite(stop) and float(row.mark_high) >= stop:
                        trigger_price, reason = stop, "stop_loss"
                    elif np.isfinite(take) and float(row.mark_low) <= take:
                        trigger_price, reason = take, "take_profit"
                if reason:
                    execute_protective_exit(timestamp, float(trigger_price), reason)

            if abs(account.quantity) > 1e-12:
                adverse_price = float(row.mark_low if account.quantity > 0 else row.mark_high)
                adverse_equity = account.equity(adverse_price)
                maintenance, _, _ = maintenance_margin(abs(account.quantity) * adverse_price)
                margin_ratio = maintenance / max(adverse_equity, 1e-12)
                max_margin_ratio = max(max_margin_ratio, margin_ratio)
                min_margin_buffer = min(min_margin_buffer, adverse_equity - maintenance)
                if adverse_equity <= maintenance:
                    execute_liquidation(timestamp, adverse_price, maintenance)

            close_equity = max(account.equity(float(row.mark_close)), 0.0)
            peak_equity = max(peak_equity, close_equity)
            if close_equity > 0:
                leverage = abs(account.quantity) * float(row.mark_close) / close_equity
                maintenance, _, _ = maintenance_margin(abs(account.quantity) * float(row.mark_close))
                max_leverage = max(max_leverage, leverage)
                min_margin_buffer = min(min_margin_buffer, close_equity - maintenance)

            boundary = timestamp + pd.Timedelta(minutes=1)
            if boundary.minute == 0 and boundary.hour % 4 == 0:
                equity_times.append(boundary)
                equity_values.append(close_equity)

    if last_row is None or last_timestamp is None:
        raise ValueError("minute_batches produced no rows")

    if abs(account.quantity) > 1e-12:
        close_delta = -account.quantity
        execution_price = float(last_row.trade_close) * (
            1 - math.copysign(config.base_slippage_bps / 10_000, account.quantity)
        )
        old_equity = account.equity(float(last_row.mark_close))
        realized, fee = account.fill(close_delta, execution_price, fee_rate)
        fills.append({
            "timestamp": last_timestamp,
            "reason": "final_close",
            "side": "sell" if close_delta < 0 else "buy",
            "quantity": abs(close_delta),
            "price": execution_price,
            "notional": abs(close_delta) * execution_price,
            "fee": fee,
            "slippage_bps": config.base_slippage_bps,
            "participation": np.nan,
            "realized_pnl": realized,
            "position_after": 0.0,
        })
        if cycle is not None:
            trade_cycles.append({
                **cycle,
                "exit_time": last_timestamp,
                "pnl": account.wallet - float(cycle["equity_before"]),
                "exit_reason": "final_close",
            })
        if equity_values:
            equity_values[-1] = account.wallet

    equity = pd.Series(equity_values, index=pd.DatetimeIndex(equity_times), name="equity")
    returns = equity.pct_change().fillna(0.0).rename("return")
    trade_frame = pd.DataFrame.from_records(trade_cycles)
    fill_frame = pd.DataFrame.from_records(fills)
    liquidation_frame = pd.DataFrame.from_records(liquidations)
    funding_frame = pd.DataFrame.from_records(funding_records)
    metrics = calculate_metrics(equity, returns.iloc[1:], trade_frame, config.periods_per_year)
    metrics.update({
        "fill_count": float(len(fill_frame)),
        "liquidation_count": float(len(liquidation_frame)),
        "fees_paid": float(account.fees_paid),
        "funding_paid": float(account.funding_paid),
        "realized_pnl": float(account.realized_pnl),
        "order_notional": float(order_notional),
        "max_leverage_observed": float(max_leverage),
        "max_margin_ratio": float(max_margin_ratio),
        "minimum_margin_buffer": float(min_margin_buffer if np.isfinite(min_margin_buffer) else 0.0),
        "max_minute_participation_observed": float(max_participation),
    })
    return MicroBacktestResult(
        equity=equity,
        returns=returns,
        fills=fill_frame,
        trades=trade_frame,
        liquidations=liquidation_frame,
        funding=funding_frame,
        metrics=metrics,
    )


def micro_period_metrics(result: MicroBacktestResult) -> dict[str, dict[str, float]]:
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
        "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
    }
    output: dict[str, dict[str, float]] = {}
    for label, (start, end) in periods.items():
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        # Equity includes the closing boundary; event logs remain half-open [start, end).
        equity = result.equity.loc[(result.equity.index >= start_ts) & (result.equity.index <= end_ts)]
        if equity.empty:
            continue
        trades = result.trades
        if not trades.empty:
            exit_time = pd.to_datetime(trades["exit_time"], utc=True)
            trades = trades.loc[(exit_time >= start_ts) & (exit_time < end_ts)]
        metrics = calculate_metrics(equity, equity.pct_change().dropna(), trades, 2190)
        fills = result.fills
        if not fills.empty:
            fill_time = pd.to_datetime(fills["timestamp"], utc=True)
            fills = fills.loc[(fill_time >= start_ts) & (fill_time < end_ts)]
        funding = result.funding
        if not funding.empty:
            funding_time = pd.to_datetime(funding["timestamp"], utc=True)
            funding = funding.loc[(funding_time >= start_ts) & (funding_time < end_ts)]
        liquidations = result.liquidations
        if not liquidations.empty:
            liquidation_time = pd.to_datetime(liquidations["timestamp"], utc=True)
            liquidations = liquidations.loc[
                (liquidation_time >= start_ts) & (liquidation_time < end_ts)
            ]
        metrics.update({
            "fill_count": float(len(fills)),
            "fees_paid": float(fills["fee"].sum()) if not fills.empty else 0.0,
            "funding_paid": float(funding["payment"].sum()) if not funding.empty else 0.0,
            "liquidation_count": float(len(liquidations)),
        })
        output[label] = metrics
    return output


def write_micro_report(
    result: MicroBacktestResult,
    params: StrategyParams,
    config: MicroBacktestConfig,
    output_dir: str | Path,
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy": params.to_dict(),
        "execution": asdict(config),
        "maintenance_brackets": [
            {"notional_cap": cap, "maintenance_rate": rate, "cumulative_deduction": cumulative}
            for cap, rate, cumulative in MAINTENANCE_BRACKETS
            if np.isfinite(cap)
        ],
        "metrics": result.metrics,
        "periods": micro_period_metrics(result),
    }
    (output / "micro_metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result.equity.to_csv(output / "micro_equity.csv", header=True)
    result.fills.to_csv(output / "micro_fills.csv", index=False)
    result.trades.to_csv(output / "micro_trades.csv", index=False)
    result.liquidations.to_csv(output / "micro_liquidations.csv", index=False)
    result.funding.to_csv(output / "micro_funding.csv", index=False)

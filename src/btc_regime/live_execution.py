"""Causal, exchange-rule-aware execution planning for V4.5.3.

The planner deliberately separates signal generation from order placement.  It
never assumes that a passive order fills: every Maker slice carries a timeout
and an IOC fallback instruction for the live adapter to execute.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


@dataclass(frozen=True)
class MarketSpec:
    """Contract filters read from the exchange before planning an order."""

    qty_step: float
    min_qty: float
    min_notional: float
    price_tick: float

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value <= 0
            for value in (self.qty_step, self.min_qty, self.min_notional, self.price_tick)
        ):
            raise ValueError("market filters must be positive")


@dataclass(frozen=True)
class LiveExecutionPolicy:
    """Execution controls for the V4.5.3 live profile.

    ``anchor_fraction`` is the fraction sent immediately as IOC for a new
    position.  The remainder is passive Maker liquidity.  Any passive order
    must be cancelled and replaced by an IOC order after ``maker_ttl_seconds``;
    the planner records this fallback but cannot submit it itself.
    """

    anchor_fraction: float = 0.25
    maker_levels: int = 3
    maker_spacing_ticks: int = 1
    maker_ttl_seconds: int = 20
    fallback: str = "ioc"
    max_spread_bps: float = 8.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.anchor_fraction) or not 0.0 <= self.anchor_fraction <= 1.0:
            raise ValueError("anchor_fraction must be within [0, 1]")
        if self.maker_levels < 1 or self.maker_spacing_ticks < 1:
            raise ValueError("maker levels and spacing must be positive")
        if self.maker_ttl_seconds < 1:
            raise ValueError("maker_ttl_seconds must be positive")
        if self.fallback != "ioc":
            raise ValueError("the only supported Maker timeout fallback is ioc")
        if not math.isfinite(self.max_spread_bps) or self.max_spread_bps <= 0:
            raise ValueError("max_spread_bps must be positive")


@dataclass(frozen=True)
class PlannedOrder:
    """One order instruction returned to a live exchange adapter."""

    side: str
    quantity: float
    order_type: str
    price: float | None
    reduce_only: bool
    post_only: bool
    timeout_seconds: int | None
    timeout_fallback: str | None
    reason: str


@dataclass(frozen=True)
class ExecutionPlan:
    """Complete target-position plan, including untradeable dust."""

    orders: tuple[PlannedOrder, ...]
    target_quantity: float
    rounded_target_quantity: float
    delta_quantity: float
    dust_quantity: float
    spread_bps: float


def _round_toward_zero(value: float, step: float) -> float:
    return math.copysign(math.floor(abs(value) / step + 1e-12) * step, value)


def _round_price(value: float, tick: float, side: str) -> float:
    # Buy prices are rounded down; sell prices are rounded up so a quote never
    # accidentally crosses the spread because of floating-point rounding.
    value_dec = Decimal(str(value))
    tick_dec = Decimal(str(tick))
    units = value_dec / tick_dec
    rounding = ROUND_FLOOR if side == "buy" else ROUND_CEILING
    return float((units.to_integral_value(rounding=rounding) * tick_dec).normalize())


def _valid_qty(quantity: float, price: float, spec: MarketSpec) -> bool:
    return (
        quantity + 1e-12 >= spec.min_qty
        and quantity * price + 1e-12 >= spec.min_notional
    )


def _split_quantity(quantity: float, count: int, step: float) -> list[float]:
    """Split a rounded quantity into step-aligned pieces without overfill."""
    if quantity <= 0:
        return []
    count = min(count, max(1, int(quantity / step + 1e-12)))
    base = _round_toward_zero(quantity / count, step)
    pieces = [base] * count
    remainder = _round_toward_zero(quantity - base * count, step)
    if pieces:
        pieces[-1] += remainder
    return [piece for piece in pieces if piece > 0]


def _ioc(side: str, quantity: float, *, reduce_only: bool, reason: str) -> PlannedOrder:
    return PlannedOrder(
        side=side,
        quantity=quantity,
        order_type="ioc",
        price=None,
        reduce_only=reduce_only,
        post_only=False,
        timeout_seconds=None,
        timeout_fallback=None,
        reason=reason,
    )


def _maker(
    side: str,
    quantity: float,
    price: float,
    policy: LiveExecutionPolicy,
    *,
    reduce_only: bool = False,
) -> PlannedOrder:
    return PlannedOrder(
        side=side,
        quantity=quantity,
        order_type="limit",
        price=price,
        reduce_only=reduce_only,
        post_only=True,
        timeout_seconds=policy.maker_ttl_seconds,
        timeout_fallback=policy.fallback,
        reason="maker_ladder",
    )


def plan_target_orders(
    current_quantity: float,
    target_quantity: float,
    best_bid: float,
    best_ask: float,
    market: MarketSpec,
    policy: LiveExecutionPolicy = LiveExecutionPolicy(),
    *,
    urgent: bool = False,
) -> ExecutionPlan:
    """Plan orders to move one net position toward a signed target.

    New exposure uses an IOC anchor plus passive Maker slices.  Any reduction,
    reversal, or urgent signal uses IOC orders so the risk reduction is not
    left resting.  The caller must submit each Maker order as post-only and
    enact its IOC fallback when the TTL expires.
    """
    if not all(math.isfinite(value) for value in (current_quantity, target_quantity, best_bid, best_ask)):
        raise ValueError("position and book values must be finite")
    if best_bid <= 0 or best_ask <= 0 or best_bid > best_ask:
        raise ValueError("best bid/ask must be positive and ordered")
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000
    if spread_bps > policy.max_spread_bps:
        urgent = True

    rounded_target = _round_toward_zero(target_quantity, market.qty_step)
    raw_delta = rounded_target - current_quantity
    side = "buy" if raw_delta > 0 else "sell" if raw_delta < 0 else "buy"
    reference = best_ask if side == "buy" else best_bid
    delta = _round_toward_zero(abs(raw_delta), market.qty_step)
    if delta <= 0 or not _valid_qty(delta, reference, market):
        return ExecutionPlan((), target_quantity, rounded_target, raw_delta, raw_delta, spread_bps)

    orders: list[PlannedOrder] = []
    current_sign = 1 if current_quantity > 0 else -1 if current_quantity < 0 else 0
    target_sign = 1 if rounded_target > 0 else -1 if rounded_target < 0 else 0
    reducing = current_sign != 0 and (
        target_sign == 0 or target_sign != current_sign or abs(rounded_target) < abs(current_quantity)
    )

    # Reversals are split into a reduce-only close and a fresh IOC entry.  A
    # single reduce-only order cannot safely cross through zero into a new side.
    if current_sign != 0 and target_sign != 0 and target_sign != current_sign:
        close_qty = _round_toward_zero(abs(current_quantity), market.qty_step)
        if _valid_qty(close_qty, reference, market):
            close_side = "sell" if current_quantity > 0 else "buy"
            orders.append(_ioc(close_side, close_qty, reduce_only=True, reason="reverse_close"))
        open_qty = _round_toward_zero(abs(rounded_target), market.qty_step)
        open_side = "buy" if rounded_target > 0 else "sell"
        if _valid_qty(open_qty, best_ask if open_side == "buy" else best_bid, market):
            orders.append(_ioc(open_side, open_qty, reduce_only=False, reason="reverse_open"))
        traded = sum(order.quantity for order in orders)
        dust = raw_delta - math.copysign(traded, raw_delta)
        return ExecutionPlan(
            tuple(orders), target_quantity, rounded_target, raw_delta, dust, spread_bps
        )

    if reducing or urgent:
        orders.append(_ioc(side, delta, reduce_only=reducing, reason="risk_reduction" if reducing else "urgent_entry"))
        return ExecutionPlan(tuple(orders), target_quantity, rounded_target, raw_delta, 0.0, spread_bps)

    anchor = _round_toward_zero(delta * policy.anchor_fraction, market.qty_step)
    if anchor > 0 and _valid_qty(anchor, reference, market):
        orders.append(_ioc(side, anchor, reduce_only=False, reason="entry_anchor"))
    else:
        # A small order should not be fragmented into untradeable pieces.
        orders.append(_ioc(side, delta, reduce_only=False, reason="small_entry"))
        return ExecutionPlan(tuple(orders), target_quantity, rounded_target, raw_delta, 0.0, spread_bps)

    maker_qty = _round_toward_zero(delta - anchor, market.qty_step)
    maker_reference = best_bid if side == "buy" else best_ask
    if not _valid_qty(maker_qty, maker_reference, market):
        order = _ioc(side, delta, reduce_only=False, reason="maker_remainder_fallback")
        return ExecutionPlan((order,), target_quantity, rounded_target, raw_delta, 0.0, spread_bps)
    pieces = _split_quantity(maker_qty, policy.maker_levels, market.qty_step)
    if not pieces or not all(_valid_qty(piece, maker_reference, market) for piece in pieces):
        order = _ioc(side, delta, reduce_only=False, reason="maker_remainder_fallback")
        return ExecutionPlan((order,), target_quantity, rounded_target, raw_delta, 0.0, spread_bps)

    for level, piece in enumerate(pieces):
        if side == "buy":
            raw_price = best_bid - level * policy.maker_spacing_ticks * market.price_tick
        else:
            raw_price = best_ask + level * policy.maker_spacing_ticks * market.price_tick
        price = _round_price(max(raw_price, market.price_tick), market.price_tick, side)
        # Ensure post-only even when the spread is one tick or the input book
        # is stale.  A quote at the wrong side is rejected instead of crossing.
        if side == "buy":
            price = min(price, _round_price(best_bid, market.price_tick, "buy"))
            if price >= best_ask:
                price = _round_price(best_ask - market.price_tick, market.price_tick, "buy")
        else:
            price = max(price, _round_price(best_ask, market.price_tick, "sell"))
            if price <= best_bid:
                price = _round_price(best_bid + market.price_tick, market.price_tick, "sell")
        if _valid_qty(piece, price, market):
            orders.append(_maker(side, piece, price, policy))
        else:
            # The whole target is sent as one IOC rather than emitting a
            # sub-minimum IOC slice for this leg.
            order = _ioc(side, delta, reduce_only=False, reason="maker_minimum_fallback")
            return ExecutionPlan((order,), target_quantity, rounded_target, raw_delta, 0.0, spread_bps)

    traded = sum(order.quantity for order in orders)
    dust = delta - traded
    return ExecutionPlan(tuple(orders), target_quantity, rounded_target, raw_delta, dust, spread_bps)


__all__ = ["ExecutionPlan", "LiveExecutionPolicy", "MarketSpec", "PlannedOrder", "plan_target_orders"]

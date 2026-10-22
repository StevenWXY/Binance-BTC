import pytest

from btc_regime.live_execution import LiveExecutionPolicy, MarketSpec, plan_target_orders


MARKET = MarketSpec(qty_step=0.001, min_qty=0.001, min_notional=5.0, price_tick=0.1)
POLICY = LiveExecutionPolicy(anchor_fraction=0.25, maker_levels=3, maker_spacing_ticks=1, maker_ttl_seconds=20)


def test_new_long_uses_ioc_anchor_and_passive_buy_ladder():
    plan = plan_target_orders(0.0, 0.2, 10000.0, 10000.1, MARKET, POLICY)
    assert plan.dust_quantity == pytest.approx(0.0)
    assert plan.orders[0].order_type == "ioc"
    assert plan.orders[0].quantity == pytest.approx(0.05)
    makers = plan.orders[1:]
    assert len(makers) == 3
    assert all(order.post_only for order in makers)
    assert all(order.side == "buy" for order in makers)
    assert all(order.price < 10000.1 for order in makers)
    assert [order.price for order in makers] == sorted((order.price for order in makers), reverse=True)
    assert all(order.timeout_fallback == "ioc" for order in makers)


def test_new_short_uses_passive_sell_ladder_above_ask():
    plan = plan_target_orders(0.0, -0.2, 10000.0, 10000.1, MARKET, POLICY)
    assert plan.orders[0].side == "sell"
    makers = plan.orders[1:]
    assert all(order.side == "sell" for order in makers)
    assert all(order.price > 10000.0 for order in makers)
    assert [order.price for order in makers] == sorted(order.price for order in makers)


def test_reduction_and_reversal_are_ioc_risk_paths():
    reduction = plan_target_orders(0.2, 0.1, 10000.0, 10000.1, MARKET, POLICY)
    assert len(reduction.orders) == 1
    assert reduction.orders[0].order_type == "ioc"
    assert reduction.orders[0].reduce_only

    reversal = plan_target_orders(0.2, -0.2, 10000.0, 10000.1, MARKET, POLICY)
    assert [order.reason for order in reversal.orders] == ["reverse_close", "reverse_open"]
    assert all(order.order_type == "ioc" for order in reversal.orders)
    assert reversal.orders[0].reduce_only
    assert not reversal.orders[1].reduce_only


def test_small_order_is_not_fragmented():
    plan = plan_target_orders(0.0, 0.001, 10000.0, 10000.1, MARKET, POLICY)
    assert len(plan.orders) == 1
    assert plan.orders[0].reason == "small_entry"
    assert plan.orders[0].order_type == "ioc"


def test_bitget_minimum_contract_size_is_supported():
    bitget = MarketSpec(qty_step=0.0001, min_qty=0.0001, min_notional=5.0, price_tick=0.1)
    plan = plan_target_orders(0.0, 0.0001, 85000.0, 85000.1, bitget, POLICY)
    assert len(plan.orders) == 1
    assert plan.orders[0].quantity == pytest.approx(0.0001)
    assert plan.orders[0].reason == "small_entry"


def test_wide_spread_forces_ioc():
    plan = plan_target_orders(0.0, 0.2, 9900.0, 10100.0, MARKET, POLICY)
    assert plan.spread_bps > POLICY.max_spread_bps
    assert len(plan.orders) == 1
    assert plan.orders[0].order_type == "ioc"

"""Print a dry-run V4.5.3 live order plan from a current L2 snapshot."""

from __future__ import annotations

import argparse
import json

from btc_regime.live_execution import LiveExecutionPolicy, MarketSpec, plan_target_orders


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-qty", type=float, required=True)
    parser.add_argument("--target-qty", type=float, required=True)
    parser.add_argument("--best-bid", type=float, required=True)
    parser.add_argument("--best-ask", type=float, required=True)
    parser.add_argument("--qty-step", type=float, required=True)
    parser.add_argument("--min-qty", type=float, required=True)
    parser.add_argument("--min-notional", type=float, required=True)
    parser.add_argument("--price-tick", type=float, required=True)
    parser.add_argument("--urgent", action="store_true")
    args = parser.parse_args()
    plan = plan_target_orders(
        args.current_qty,
        args.target_qty,
        args.best_bid,
        args.best_ask,
        MarketSpec(args.qty_step, args.min_qty, args.min_notional, args.price_tick),
        LiveExecutionPolicy(),
        urgent=args.urgent,
    )
    print(json.dumps({
        "target_quantity": plan.target_quantity,
        "rounded_target_quantity": plan.rounded_target_quantity,
        "delta_quantity": plan.delta_quantity,
        "dust_quantity": plan.dust_quantity,
        "spread_bps": plan.spread_bps,
        "orders": [order.__dict__ for order in plan.orders],
    }, indent=2))


if __name__ == "__main__":
    main()

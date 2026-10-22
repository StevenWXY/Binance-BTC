# V4.6.2 research protocol — frozen before new candidate replays

Date: 2026-10-20. Baseline is the existing V4.6.1 with 0.90 exposure.
Data: existing Bitget 2020-01-01 through 2026-10-11 08:00 UTC cache.
All history has previously been visible; no blind holdout claim.

Fees are inherited account assumptions: Maker 2 bps, Taker 6 bps gross,
60% rebate gives 0.8 / 2.4 bps net. Rebate is immediately netted.
Current account tier and rebate settlement timing are not verified.

Maker treatment: fixed 1 bps limit, eligible only after one 5m bar,
strict penetration of another 1 bps, capacity 25% of the standard 2% bar
participation cap, 15-minute expiry with Taker fallback. Risk reductions,
protective exits and final close are Taker. Not order-book queue replay.

Eight candidates, no Cartesian search:
1. control_taker: exact V4.6.1.
2. control_maker: signal unchanged, resting Maker implementation.
3. risk85_maker: exposure 0.85.
4. break4_risk85: 4h instead of 6h long breakout at exposure 0.85.
5. cooldown1_risk85: 1h instead of 3h long cooldown at exposure 0.85.
6. hold48_risk85: 48h instead of 72h long maximum hold at exposure 0.85.
7. trail25_risk85: 2.5 instead of 3.0 ATR long trailing distance at exposure 0.85.
8. reclaim_risk85: long EMA reclaim without repeated high-breakout entries, exposure 0.85.

Selection uses 2020–2023 and 2024–2025 only, then locks the choice.
2026 is a contaminated chronological diagnostic, never a reselection set.
Guard: both folds profitable; combined daily Sharpe and positive-month fraction
at least baseline; combined CAGR >=50%; drawdown magnitude <=22%;
trade frequency between baseline and 1.6 times baseline.
Score: mean of train/validation daily Sharpes minus 0.25 times their absolute
difference plus 0.5 times development positive-month fraction.
Within 0.03 score prefer fewer parameter changes.
If none passes, report tradeoffs without expanding the search.

Stress: all Taker, 3 bps penetration and 10% capacity, no rebate (6/2 bps),
double slippage/impact, extra 1h signal latency, adverse 1 bp carry per 8h
on every position before observed funding coverage. The last is synthetic
stress only and is never labeled historical funding.
Adjacent signal parameter and exposure tests are diagnostics only.
Every attempted variant and failed check is retained.

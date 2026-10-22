# Post-screen execution hypothesis — not part of the frozen eight

The eight-candidate screen failed on 2020–2025. That failure and its lock remain.
After inspecting those results and the 2026 diagnostics, test exactly one new
execution policy: the whole initial exposure instruction is Taker, including
partial fills; only additions to an existing same-direction position may rest
Maker. Reductions/reversals/stops remain Taker. All V4.6.1 signal parameters,
0.90 exposure, 60% rebate, quote offset, queue proxy and expiry stay unchanged.

Rationale: preserve timing of first trend entry while saving fees on less
urgent additions. This is adaptive hypothesis generation on already-seen data,
not a fresh holdout result. No entry/frequency/leverage parameters are reselected.
Development is 2020–2025; 2026 is reported separately. Full replay, cost stress,
and exposure 0.85/0.95 are diagnostics only if the mechanism is promising.
The baseline is retained unless full CAGR, daily Sharpe and positive-month share
all improve, with close-equity maximum drawdown no worse than approximately 22%.
Trade count is disclosed; raising fills through partial orders is not counted as
an increase in independent strategy opportunities.

An engine edge case is also corrected: an expired resting order encountering
zero bar volume remains eligible for its configured Taker fallback once volume
returns; it is no longer silently discarded by the old Maker timeout branch.
This is a correctness repair, not a parameter optimization. Frozen results are
regression-checked against the repaired engine.

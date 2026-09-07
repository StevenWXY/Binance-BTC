# Governor Redesign Review

## Goal

Reduce the account-level governor's tendency to cut bull-market long exposure too early, while preserving live-like risk controls.

## What Changed

1. `reduce_only_level_3` semantics were corrected in `live_risk.py`:
   - before: level-3 drawdown effectively pushed same-side targets toward `0`
   - now: level-3 truly means "can reduce, cannot add"
2. A continuation reentry ladder was added:
   - reentry is only considered after drawdown has recovered by a configurable buffer
   - the best execution variant only reopens capacity in `level_2 / level_1`
   - `level_3` remains no-add

## Files

- `src/btc_regime/live_risk.py`
- `src/btc_regime/micro_backtest.py`
- `tests/test_live_risk.py`
- `configs/v71_final_candidate_governor_reentry_execution.json`
- `reports/governor_redesign_baseline_live_like_2020_2026_08_01/`
- `reports/governor_reentry_live_like_2020_2026_08_01/`
- `reports/governor_reentry_scan_2020_2026_08_01/`
- `reports/governor_reentry_bull_suppression_2020_2026_08_01/`

## Compare

Baseline here means the old execution config running on the new corrected governor semantics, but with continuation reentry disabled.

| Variant | Total Return | Sharpe | Calmar | Max DD | Final Equity |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline semantic fix | 22.15% | 0.3109 | 0.1754 | -17.60% | 12214.63 |
| Best reentry (`level2_only`) | 23.01% | 0.3193 | 0.1815 | -17.61% | 12300.68 |

## Annual Notes

- `2020`: `22.92% -> 23.73%`
- `2023`: `1.90% -> 1.90%` (almost unchanged, slight improvement)
- `2025`: `2.28% -> 2.32%`
- `2026`: `0.32% -> 0.34%`

The redesign does not transform the strategy, but it improves the governor without paying a material drawdown penalty.

## Bull Suppression Diagnosis

The earlier diagnosis remains directionally valid:

- disabling `price_drawdown_scale` helps a little
- disabling the account governor changes results by an order of magnitude

That means the governor is still the dominant long-suppression layer.

## Recommendation

Use `configs/v71_final_candidate_governor_reentry_execution.json` as the current preferred execution config for the long-participation candidate.

Do not use level-3 continuation reentry for now. The scan showed that allowing reentry while still in level 3 tends to worsen 2026-like paths faster than it helps bull recovery.

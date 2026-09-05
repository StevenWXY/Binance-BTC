# Project Handoff

## Current State

- Repository: `https://github.com/StevenWXY/Binance-BTC.git`
- Active branch: `xuyujian修改`
- Remote `main` must not be overwritten unless the user explicitly requests it.
- Latest pushed commit before this handoff: `2cbc1dc`.
- The working tree contains many historical experiments and generated reports. Do not delete, reset, or clean unrelated user files.
- The local friend dataset is `D:\文档\桌面\data.zip`. Its nested ZIP members must be read in memory because direct extraction can produce `%TSD-Header-###%` wrapper corruption.

## Completed Goals

1. Installed and tested the Python project dependencies.
2. Added local friend-data loading for 4h candles, 1m trade candles, 1m mark price, and funding data.
3. Aligned the 1m execution backtest with the friend's README V4 result: V4 ends at `$417,797.65` from `$10,000` over `2020-01-01` to `2026-08-01`.
4. Compared V4, V4.1, V4.2 direction strategy, and the historical high-profit V7 using the same friend dataset and execution assumptions.
5. Optimized V7 into V7.1 and pushed it to branch `xuyujian修改`.
6. Added V7.1 strategy parameters, execution drawdown controls, README documentation, comparison results, parameter search, and validation scripts.
7. Test status after V7.1.3: `32 passed`.

## Strategy Versions

### V4

Long-only adaptive trend/rebound baseline from `configs/aggressive_adaptive_v3_params.json`.

### V4.1

Refined V4 from `configs/v4_refined_params.json`.

### V4.2

Direction strategy from the friend's validated version. In the current unified comparison, only `configs/v4_2_params.json` direction logic is compared. The separate V4.2 neutral funding-arbitrage capital overlay is intentionally excluded.

### V7

The historical profit-focused V7 parameters are from commit `95774d0`. It uses mutually exclusive `range`, `trend_up`, and `trend_down` states on 4h bars, 4h trend/range signals, ATR volatility sizing, rapid-move controls, and symmetric short logic. The old high-profit V7 parameter file is not the current working-tree `configs/v7_params.json`; use the historical file or `configs/v71_params.json` as appropriate.

### V7.1

V7.1 is stored in `configs/v71_params.json`. Compared with the historical high-profit V7:

- `trend_trailing_stop_atr = 2.0`
- `breakout_buffer_atr = 0.2`
- `short_scale = 0.15`

V7.1 also uses the execution-layer drawdown overlay in `configs/v71_execution.json`:

- strategy equity drawdown >= 20%: target exposure x `0.95`
- >= 30%: target exposure x `0.85`
- >= 40%: target exposure x `0.70`

The overlay changes target position sizing only. It does not alter the V7 market-state classifier. The original V7 configuration remains preserved.

## Unified Backtest

Dataset: friend `data.zip`.

Period: `2020-01-01` through `2026-08-01`.

Initial cash: `$10,000`.

Execution: 4h signal generation, 1m trade and mark-price execution, 4 bps taker fee, 1 bps base slippage, 8 bps impact, 2% maximum minute participation, funding payments, maintenance-margin checks, and no liquidations in the reported runs.

| Strategy | Final equity | CAGR | Sharpe | Max drawdown |
| --- | ---: | ---: | ---: | ---: |
| V4 | $417,797.65 | 76.31% | 1.498 | -30.78% |
| V4.1 | $439,110.94 | 77.65% | 1.516 | -30.83% |
| V4.2 direction | $206,483.88 | 58.41% | 1.533 | -23.68% |
| V7 | $561,729.69 | 84.42% | 1.436 | -40.18% |
| V7.1 | $728,076.22 | 91.84% | 1.541 | -38.30% |

V7.1 is a historical candidate, not a guarantee of future performance. Its full-period result improved over V7, but the absolute drawdown remains high. The holdout `2025-01` to `2026-07` V7.1 drawdown was about `-28.47%`, with Sharpe about `0.535`.

## Important Files

- `configs/v71_params.json`: V7.1 strategy parameters.
- `configs/v71_execution.json`: V7.1 execution and drawdown overlay parameters.
- `configs/v712_params.json` / `configs/v712_execution.json`: V7.1.2 protection, maker, and 30% rebate parameters.
- `src/btc_regime/v712.py`: V7.1.2 causal ATR protection and fast downside exit.
- `scripts/backtest_v712.py`: full V7.1/V7.1.2 minute-level comparison runner.
- `reports/v712_micro_2020_2026_07/`: V7.1.2 full-period backtest outputs.
- `configs/v713_params.json` / `configs/v713_execution.json`: V7.1.3 lower-leverage parameters.
- `src/btc_regime/v713.py` and `scripts/backtest_v713.py`: V7.1.3 implementation and backtest runner.
- `reports/v713_micro_2020_2026_07/`: V7.1.3 full-period backtest outputs, including the V4.2.1 neutral sleeve.
- `configs/v713_capital_params.json`: V4.2.1-style neutral capital allocation and recall thresholds.
- `src/btc_regime/v42.py`: causal settled-funding neutral sleeve reused by V7.1.3.
- `scripts/compare_six_strategies_btc.py`: unified V4/V7 six-strategy replay with BTC baseline and SVG curves.
- `reports/unified_v4_v7_btc_2020_2026_08_01/`: unified metrics, equity/drawdown curves, and per-strategy details.
- `src/btc_regime/v7.py`: V7/V7.1 signal logic, including ATR breakout buffer.
- `src/btc_regime/micro_backtest.py`: 1m execution, funding, margin, and optional equity drawdown scaling.
- `scripts/compare_v4_v7_micro_local.py`: unified V4/V4.1/V4.2/V7/V7.1-compatible local comparison runner.
- `scripts/optimize_v7_risk_round4.py`: constrained V7 risk-parameter search.
- `scripts/validate_v7_candidate_4h.py`: parameter-neighborhood and period validation.
- `reports/v4_v41_v42_v7_v71_micro_friend_2020_2026_07/`: unified comparison metadata and metrics.
- `reports/v7_equity_drawdown_overlay_late_clean_micro_friend_2020_2026_07/`: V7.1 detailed micro-backtest output.

## Pending Work

1. Diagnose V7.1.3's remaining drawdown by aligning equity drawdown troughs with 4h market state, signal direction, leverage, funding, and fills.
2. Run maker fill-rate, quote-offset, timeout, and adverse-selection sensitivity tests; historical OHLC touch fills are only a deterministic proxy for order-book execution.
3. Re-run candidate tests with a proper walk-forward design: select on 2020-2022, validate on 2023-2024, and keep 2025-2026 as untouched holdout.
4. Add boundary tests for V7.1.3 protection triggers, account drawdown scaling, and neutral recall transitions.
5. Do not make V7.1.3 the project-wide default until execution sensitivity and walk-forward validation are complete.
6. Future pushes should normally target `xuyujian修改`; synchronize with `main` only after explicit user approval.

## Verification Commands

```powershell
pytest -q
python -m py_compile src/btc_regime/v7.py src/btc_regime/micro_backtest.py scripts/compare_v4_v7_micro_local.py
```

The full friend-data micro backtest is expensive. Use `--source-zip D:\文档\桌面\data.zip` and do not use damaged direct-extraction copies.

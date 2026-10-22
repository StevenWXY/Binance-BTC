# V4.5.5 Bitget 参数微调报告

选择候选：`bg_d`。基线为 V4.5.3 的 Bitget 回放。
参数选择同时要求验证窗口 Sharpe、2024 年后 Sharpe 和 2024 年后收益不低于基线，且 holdout 回撤不超过 30%。

| 窗口 | 指标 | V4.5.3 | V4.5.5 | 变化 |
|---|---|---:|---:|---:|
| full | total_return | 5465.73% | 5230.09% | -235.64% |
| full | sharpe | 1.552 | 1.542 | -0.011 |
| full | max_drawdown | -30.43% | -34.12% | -3.69% |
| full | cycles_per_year | 74.297 | 72.626 | -1.671 |
| post2024 | total_return | 293.16% | 331.83% | +38.67% |
| post2024 | sharpe | 1.494 | 1.593 | +0.098 |
| post2024 | max_drawdown | -22.74% | -22.73% | +0.01% |
| post2024 | cycles_per_year | 72.433 | 70.497 | -1.937 |
| post2025 | total_return | 147.53% | 186.27% | +38.74% |
| post2025 | sharpe | 1.701 | 1.960 | +0.259 |
| post2025 | max_drawdown | -22.49% | -22.49% | -0.00% |
| post2025 | cycles_per_year | 71.536 | 69.004 | -2.532 |
| validation | total_return | 118.31% | 119.28% | +0.97% |
| validation | sharpe | 1.386 | 1.397 | +0.012 |
| validation | max_drawdown | -22.74% | -22.73% | +0.01% |
| validation | cycles_per_year | 72.788 | 70.117 | -2.671 |
| holdout | total_return | 80.09% | 96.92% | +16.84% |
| holdout | sharpe | 1.706 | 1.959 | +0.254 |
| holdout | max_drawdown | -22.49% | -22.49% | -0.00% |
| holdout | cycles_per_year | 71.951 | 71.028 | -0.922 |

参数变化：空头 entry 从 `break8` 调整为 `break12`，其余信号参数保持 V4.5.3。
手续费使用 Bitget 标准费率的 60% 返佣后数值：taker 2.4 bps、maker 0.8 bps。
资金费率仅有 2026-06-27 至 2026-07-31 的公开数据，未用估算值补齐早期区间。

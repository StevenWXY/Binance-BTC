# Risk-Adjusted Plus Review

本轮是在上一版 `risk-adjusted` 基础上继续做的局部优化，目标是：

- 保住 `wzy` 当前相对 `main` 的风险优势；
- 尽量修补 `2021 / 2024 / 2026` 这些偏弱年份；
- 继续抬高 `Sharpe / Calmar`。

最终落地的新候选：

- 参数：[v71_final_candidate_risk_adjusted_plus_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_plus_params.json)
- 执行：[v71_final_candidate_risk_adjusted_plus_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_plus_execution.json)

## 1. 这次具体改了什么

相对上一版 `risk-adjusted`，只改了两处：

- `breakout_buffer_atr: 0.20 -> 0.21`
- `trailing_stop_atr: 1.70 -> 1.60`

也就是说，这一版不是大改结构，而是：

- 让趋势入场稍微更谨慎一点；
- 同时让持仓退出更快一点。

## 2. 为什么要这样改

上一版 `risk-adjusted` 的弱点已经很明确：

- `2021`
- `2024`
- `2026 YTD`

这几个弱年份主要不是 `short` 拖累，而是 `long` 亏损。

对应诊断结论是：

- 不能继续一味压 `short`；
- 更应该修 `long` 在弱趋势 / 假突破环境下的入场与退出质量。

## 3. Three-Branch Same-Basis

来源文件：[summary_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_same_basis_risk_adjusted_plus_2020_2026_08_01/summary_metrics.csv)

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `306.75%` | `1.0655` | `1.1493` | `-20.67%` |
| `wzy_v71_risk_adjusted_plus` | `119.48%` | `0.7261` | `0.7096` | `-17.88%` |
| `xuyujian_v71_ref` | `80.73%` | `0.6128` | `0.4082` | `-23.05%` |

解读：

- `wzy` 继续稳稳超过 `xuyujian`。
- 同时，`wzy` 相对 `main` 仍然保有更浅的全样本回撤。

## 4. Three-Branch Live-Like

来源文件：[summary_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_live_like_risk_adjusted_plus_2020_2026_08_01/summary_metrics.csv)

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy_v71_risk_adjusted_plus` | `118.95%` | `0.7205` | `0.7071` | `-17.88%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- `wzy` 依然没有追上 `main` 的 `Sharpe / Calmar`。
- 但它相对 `main` 的优势还在，而且比上一版又更强了一点：
  - 更低波动
  - 更低回撤
  - 更高 maker fill ratio
  - 更低资金费拖累

## 5. 当前 `wzy` 相对 `main` 的优势

在最新 live-like 横比里，`wzy` 相对 `main` 的主要优势是：

1. 风险更低
   - `annualized_volatility`: `0.1906 < 0.2322`
   - `max_drawdown`: `-17.88% > -19.13%`
   - `governor_max_drawdown_observed`: `0.1839 < 0.1940`

2. 执行摩擦更小
   - `maker_fill_ratio`: `0.7620 > 0.5613`
   - `funding_paid`: `1464 < 4786`

3. 杠杆使用更克制
   - `max_leverage_observed`: `4.54 < 6.20`

4. 交易质量更稳
   - `win_rate`: `38.41% > 33.85%`

一句话概括就是：

**`wzy` 相对 `main` 的优势，是“更稳、更省摩擦、更克制”，而不是“更能赚钱”。**

## 6. 相对上一版 `risk-adjusted` 的改进

上一版 live-like：

- `total_return = 96.60%`
- `Sharpe = 0.6498`
- `Calmar = 0.5969`
- `Max DD = -18.12%`

这版 live-like：

- `total_return = 118.95%`
- `Sharpe = 0.7205`
- `Calmar = 0.7071`
- `Max DD = -17.88%`

对应变化：

- `total_return`: `+22.34 pct`
- `Sharpe`: `+0.0707`
- `Calmar`: `+0.1102`
- `Max DD`: `+0.24 pct`（更浅）

这说明这轮轻量微调是有效的，而且不是靠牺牲回撤换来的。

## 7. 年度结构变化

来源文件：[annual_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/final_candidate_risk_adjusted_plus_live_like_2020_2026_08_01/annual_metrics.csv)

| year | total_return | sharpe | max_drawdown |
| --- | ---: | ---: | ---: |
| `2020` | `27.31%` | `1.0985` | `-14.71%` |
| `2021` | `-5.79%` | `-0.5345` | `-12.44%` |
| `2022` | `-1.20%` | `-0.1268` | `-6.07%` |
| `2023` | `69.18%` | `1.7709` | `-11.74%` |
| `2024` | `6.66%` | `0.4173` | `-17.88%` |
| `2025` | `1.17%` | `0.2070` | `-4.06%` |
| `2026 YTD` | `1.20%` | `0.2282` | `-6.65%` |

解读：

- 最大的改善来自：
  - `2024: -4.67% -> +6.66%`
  - `2026 YTD: -2.92% -> +1.20%`
- `2023` 仍然保持了强趋势年份的主盈利能力，没有被明显破坏。
- `2021` 还是弱点，但已经比上一版略好。

## 8. 当前结论

如果只回答“现在 `wzy` 相对 `main` 的优势是什么”：

**答案是：更低的波动、更浅的回撤、更高的 maker 成交占比、更低的资金费拖累。**

如果回答“这轮继续优化有没有实质进展”：

**有，而且是实打实的进展。**

- `wzy` 还没追上 `main` 的 `Sharpe / Calmar`
- 但已经在保持自身风险优势的前提下，把这两个指标继续往上推了一截

## 9. 下一步建议

下一轮最值得继续攻的还是 `2021`。

因为现在：

- `2024` 已经转正
- `2026 YTD` 已经转正
- `2023` 保住了

剩下最明显的弱点就是：

- `2021` 仍然偏弱

所以后面如果继续优化，我建议聚焦：

1. `2021` 的 long stop-loss 质量
2. 假突破后的更早去风险
3. 尽量不破坏 `2023` 的趋势持有能力

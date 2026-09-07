# Risk-Adjusted Priority Review

这轮优化的目标很明确：

**优先把 `wzy` 的 `Sharpe` 或 `Calmar` 做到比参考分支更优，收益率允许适当牺牲。**

本轮最终落成的新候选：

- 参数：[v71_final_candidate_risk_adjusted_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_params.json)
- 执行：[v71_final_candidate_risk_adjusted_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_execution.json)

本轮新增扫描脚本：

- [scan_risk_adjusted_priority.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/scripts/scan_risk_adjusted_priority.py)

结果目录：

- same-basis: [three_branch_same_basis_risk_adjusted_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_same_basis_risk_adjusted_2020_2026_08_01)
- live-like: [three_branch_live_like_risk_adjusted_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_live_like_risk_adjusted_2020_2026_08_01)
- 单独年度包：[final_candidate_risk_adjusted_live_like_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/final_candidate_risk_adjusted_live_like_2020_2026_08_01)

## 1. 结论先行

- 这轮目标已经完成了一大半：`wzy` 新候选在 `same-basis` 和 `live-like` 两套横比里，都已经同时超过 `xuyujian_v71_ref` 的 `Sharpe` 与 `Calmar`。
- 但它还没有超过 `main_v43`。如果把目标理解为“必须压过两个参考分支中的最强者”，那目前仍未达成。
- 这轮真正有效的，不是继续把 `short` 一路压到几乎关闭，而是 **整体降低风险预算**：
  - `target_vol: 0.97 -> 0.82`
  - `trend_scale: 1.60 -> 1.35`
- 也就是说，这次最有效的方向更像是：
  - 保留原有结构；
  - 把总暴露压回一个更稳、更能穿越的区间；
  - 而不是继续对局部模块做极端收缩。

## 2. 新候选相对上一版的核心变化

相对上一版 `2023-targeted`：

- `target_vol: 0.97 -> 0.82`
- `trend_scale: 1.60 -> 1.35`
- `long_permission_scale: 1.14 -> 1.08`
- 其余执行层保持不变，仍沿用：
  - `continuation reentry`
  - `maker`
  - `recovery probe`
  - 账户级 governor

这说明当前更像是“先把全局风险杠杆降下来，再看结构会不会自己变健康”，而不是继续单点拧 `short`。

## 3. Three-Branch Same-Basis

来源文件：[summary_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_same_basis_risk_adjusted_2020_2026_08_01/summary_metrics.csv)

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `306.75%` | `1.0655` | `1.1493` | `-20.67%` |
| `wzy_v71_risk_adjusted` | `95.73%` | `0.6472` | `0.5788` | `-18.56%` |
| `xuyujian_v71_ref` | `80.73%` | `0.6128` | `0.4082` | `-23.05%` |

解读：

- 在统一基础执行口径下，`wzy` 已经超过 `xuyujian`：
  - `Sharpe`: `0.6472 > 0.6128`
  - `Calmar`: `0.5788 > 0.4082`
- 同时 `Max DD` 也比 `xuyujian` 更小：
  - `-18.56%` vs `-23.05%`
- 这说明当前 `wzy` 已经不只是“更保守”，而是开始体现出更好的风险收益比。

## 4. Three-Branch Live-Like

来源文件：[summary_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_live_like_risk_adjusted_2020_2026_08_01/summary_metrics.csv)

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy_v71_risk_adjusted` | `96.60%` | `0.6498` | `0.5969` | `-18.12%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- 在更贴近实盘的 live-like 口径下，`wzy` 也同样超过 `xuyujian`：
  - `Sharpe`: `0.6498 > 0.6294`
  - `Calmar`: `0.5969 > 0.4365`
- 而且它没有靠“躺平不交易”来换风报：
  - `trade_count = 422`
  - `maker_fill_ratio = 0.7495`
- 这意味着这轮改动不是单纯把系统关小，而是找到了一个更健康的风险预算区间。

## 5. 相对上一版 `2023-targeted` 的改进

上一版 live-like 结果：

- `total_return = 37.73%`
- `Sharpe = 0.4028`
- `Calmar = 0.2914`
- `Max DD = -17.10%`

新候选 live-like 结果：

- `total_return = 96.60%`
- `Sharpe = 0.6498`
- `Calmar = 0.5969`
- `Max DD = -18.12%`

对应变化：

- `total_return`: `+58.88 pct`
- `Sharpe`: `+0.2470`
- `Calmar`: `+0.3056`
- `Max DD`: `-1.02 pct`（略有变差，但在可接受范围内）

这组数字的含义是：

- 新候选不是靠大幅缩收益换来一点风报提升；
- 反而是 **收益和风报一起改善**，只是回撤比上一版略大一点。

## 6. 年度结构检查

来源文件：[annual_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/final_candidate_risk_adjusted_live_like_2020_2026_08_01/annual_metrics.csv)

| year | total_return | sharpe | max_drawdown |
| --- | ---: | ---: | ---: |
| `2020` | `33.19%` | `1.2653` | `-14.47%` |
| `2021` | `-6.66%` | `-0.5879` | `-13.68%` |
| `2022` | `-0.95%` | `-0.0628` | `-7.08%` |
| `2023` | `71.59%` | `1.8017` | `-12.47%` |
| `2024` | `-4.67%` | `-0.2198` | `-17.83%` |
| `2025` | `0.53%` | `0.1110` | `-4.10%` |
| `2026 YTD` | `-2.92%` | `-0.9862` | `-4.03%` |

解读：

- 当前最明显的改善来自 `2023`，这一年从此前“偏弱参与”转成了真正的主力盈利年。
- `2020` 依然贡献较大，但系统已经不再只靠 `2020` 一年吃饭。
- 残留短板也很清楚：
  - `2021`
  - `2024`
  - `2026 YTD`
  这些年份仍然偏弱。

## 7. 这轮为什么有效

从这次结果看，最近几轮里一个容易踩的误区是：

- 看到 `short` 拖累，就继续一味压 `short`
- 看到回撤敏感，就继续一味收紧 governor

但这轮数据说明，至少对当前结构来说，更有效的路径反而是：

1. 不要把局部模块压得过头。
2. 先把总暴露降回更合理的区间。
3. 让系统在强趋势里还能持续参与，但不再过度放大。

也就是：

**当前 `wzy` 更像是“总风险预算过高导致风报失真”，而不是“单个方向模块还不够紧”。**

## 8. 当前结论

如果按“至少要比参考线更优的 Sharpe 或 Calmar”这个目标看：

- 对 `xuyujian_v71_ref`：已经达成，而且是 `Sharpe + Calmar` 双双超过。
- 对 `main_v43`：还没有达成。

所以现在更准确的结论是：

**`wzy` 已经从“风报落后”推进到“超过 xuyujian、但仍未追平 main”的阶段。**

## 9. 下一步建议

下一轮如果还要继续往上推，我建议重点看两件事：

1. 专门修 `2021 / 2024 / 2026 YTD` 这些弱年份，而不是再泛扫全样本。
2. 在保持当前总风险预算大体不变的前提下，微调：
   - `trend_confirm_bars`
   - `breakout_buffer_atr`
   - `long_continuation_threshold`

也就是说，下一轮更像应该是：

**先固定这版 risk-adjusted 总风险框架，再做弱年份定向修补。**

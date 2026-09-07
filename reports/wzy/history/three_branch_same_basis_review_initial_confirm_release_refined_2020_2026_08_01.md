# Three-Branch Same-Basis Review: Initial Confirm Release Refined

这份文档用于替代早期围绕 `2023_targeted` 候选的三分支复核说明，当前主线已经切换到：

- 参数：[v71_final_candidate_initial_confirm_release_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_release_refined_params.json)
- 执行：[v71_final_candidate_initial_confirm_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_execution.json)
- 结果目录：[initial_confirm_release_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_release_refined_validation_2020_2026_08_01)

这轮复核的重点不是再讨论 `2023_targeted` 是否有效，而是确认：

1. `initial_confirm_release_refined` 是否已经成为 `wzy` 当前最强候选；
2. 它在三分支横比里处于什么位置；
3. 它是否已经满足“保守但风报至少优于参考分支”的目标。

## 1. 结论先行

- 当前 `wzy` 主候选已经从早期的 “2023_targeted” 路线，转到 `initial_confirm_release_refined`。
- 在最新 same-basis 复核里，`wzy` 已经**稳定强于 `xuyujian_v71_ref`**：
  - `Sharpe 0.8572 > 0.6294`
  - `Calmar 0.9253 > 0.4365`
  - `Max DD -17.10% > -23.06%`
- 相比 `main_v43`，`wzy` 仍然落后，但差距比更早阶段已经明显收窄。
- 因此，按照目前用户强调的标准，`wzy` 已经不再是“更保守但风报也更差”的分支，而是进入了“**保守且风报显著强于 xuyujian，但仍未追平 main**”的阶段。

## 2. 口径说明

本轮三分支复核来源于：

- [same_basis/summary_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_release_refined_validation_2020_2026_08_01/same_basis/summary_metrics.csv)
- [same_basis/report.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_release_refined_validation_2020_2026_08_01/same_basis/report.json)

这里的 “same-basis” 含义是：

- 三个分支都跑在同一套执行配置下；
- 执行配置使用当前 `wzy` 主候选的实盘口径执行基线；
- 因此这份横比反映的是“同一执行口径下，策略本体谁更强”，而不是各自挑自己最舒服的 execution 去比赛。

## 3. 全样本三分支结果

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy initial_confirm_release_refined` | `163.03%` | `0.8572` | `0.9253` | `-17.10%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- `main_v43` 仍是当前三者里最强的绝对参考线。
- `wzy` 已经稳居第二，并且不是靠“单纯压仓”取胜：
  - 收益明显高于 `xuyujian`
  - `Sharpe / Calmar` 也同步高于 `xuyujian`
  - 回撤还更浅
- `xuyujian_v71_ref` 现在更适合作为“已被当前 `wzy` 超过的参考基线”，而不是 `wzy` 当前仍未翻越的门槛。

## 4. 分层结果

### 4.1 训练段 `2020-2022`

- `total_return = 24.94%`
- `Sharpe = 0.5505`
- `Calmar = 0.5327`
- `Max DD = -14.46%`

训练段不是特别激进，但比较稳定。

### 4.2 验证段 `2023-2024`

- `total_return = 84.73%`
- `Sharpe = 1.3004`
- `Calmar = 2.0980`
- `Max DD = -17.10%`

验证段是这轮最强的一层，说明 release 修正之后，`initial_confirm` 对中高质量趋势段的参与效率明显变好了。

### 4.3 留出段 `2025-2026_07`

- `total_return = 13.97%`
- `Sharpe = 0.6376`
- `Calmar = 1.1724`
- `Max DD = -7.36%`

留出段仍保持正收益和正风报，而且 `Calmar > 1.0`。这意味着当前候选不是只在训练/验证集里好看，留出段也站住了。

## 5. 相对上一阶段的变化

如果把当前结果和更早的 `initial_confirm` 阶段相比，最关键的改进不是新加了更多机制，而是：

- 把 `initial_confirm` 的 **release 语义** 补齐
- 当 early confirmed-long 的缩放结束时，强制 rebalance 回正常仓位

这件事让当前主候选的核心指标进一步抬升到：

- `Sharpe 0.8122 -> 0.8572`
- `Calmar 0.8463 -> 0.9253`
- `total_return 144.53% -> 163.03%`

所以当前文档体系里，`initial_confirm_release_refined` 才是应该被视为主候选的版本，而不是更早那版 `initial_confirm`。

## 6. 对当前 `wzy` 的判断

### 6.1 已经实现的目标

- `wzy` 不再只是“更保守但风报更弱”。
- 在当前标准验证口径下，`wzy` 已经显著强于 `xuyujian_v71_ref`。
- `wzy` 维持了更低回撤，同时把收益和风报一起抬了上来。

### 6.2 仍未实现的目标

- `wzy` 距离 `main_v43` 仍有明显差距：
  - `Sharpe 0.8572 vs 1.1053`
  - `Calmar 0.9253 vs 1.3481`
- 也就是说，当前 `wzy` 已经完成“超过 xuyujian”这一阶段目标，但还没有完成“追平或超过 main”。

## 7. 当前推荐阅读顺序

如果现在要了解 `wzy` 当前状态，建议按这个顺序读：

1. [initial_confirm_release_refined_review_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/initial_confirm_release_refined_review_2020_2026_08_01.md)
2. 本文档
3. [initial_confirm_release_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_release_refined_validation_2020_2026_08_01)

## 8. 当前结论

用一句话概括当前状态：

**`initial_confirm_release_refined` 已经把 `wzy` 推进到“显著强于 xuyujian、仍落后于 main”的新阶段，并且它应当取代所有更早阶段候选，成为当前文档与验证的唯一主候选。**

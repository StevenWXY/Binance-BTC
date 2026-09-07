# Three-Branch Same-Basis Review: Initial Confirm Continuation Short Longstrong

当前 `wzy` 主候选已经从 `initial_confirm_continuation_short_refined` 继续推进到：

- 参数：[v71_final_candidate_initial_confirm_continuation_short_longstrong_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_continuation_short_longstrong_params.json)
- 执行：[v71_final_candidate_initial_confirm_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_execution.json)
- 结果目录：[initial_confirm_continuation_short_longstrong_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_validation_2020_2026_08_01)

这轮 same-basis 复核关注的是：

1. strong-long protection 是否真的带来净增益；
2. 它是否进一步抬升 `Sharpe / Calmar`；
3. 它是否继续保住 `wzy` 的低回撤特征。

## 1. 全样本三分支结果

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy initial_confirm_continuation_short_longstrong` | `216.40%` | `0.9765` | `1.1149` | `-17.15%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- `wzy` 继续稳定高于 `xuyujian`
- `wzy` 仍低于 `main`
- 但相较上一版 `short_refined`，`wzy` 又显著往前迈了一步

## 2. 相对上一版主候选

上一版 `continuation_short_refined`：

- `Sharpe = 0.9306`
- `Calmar = 1.0459`
- `Max DD = -17.08%`

当前版 `continuation_short_longstrong`：

- `Sharpe = 0.9765`
- `Calmar = 1.1149`
- `Max DD = -17.15%`

这次的形状是：

- 风报显著更高
- 收益更高
- 回撤只略差一点点

所以它不是“小修小补”，而是一次明确的主候选升级。

## 3. 分层结果

### 训练段 `2020-2022`

- `Sharpe = 0.6166`
- `Calmar = 0.6254`

### 验证段 `2023-2024`

- `Sharpe = 1.4066`
- `Calmar = 2.3594`

### 留出段 `2025-2026_07`

- `Sharpe = 0.9083`
- `Calmar = 1.9749`

这轮最大的加分点在：

- 验证段继续抬升
- 留出段明显抬升

## 4. 当前判断

这轮 strong-long protection 说明了一件事：

- `wzy` 当前 long 的问题已经不在 early leg
- 而在 high-quality continuation 的保护仍偏紧

所以这轮优化不是 broad risk budget 调整，而是对 strong-long 持仓语义的进一步校准。

## 5. 当前结论

**`initial_confirm_continuation_short_longstrong` 应当取代 `initial_confirm_continuation_short_refined`，成为当前 `wzy` 的正式三分支复核主候选。**

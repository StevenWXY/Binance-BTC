# Three-Branch Same-Basis Review: Initial Confirm Continuation Short Refined

当前 `wzy` 主候选已经从 `initial_confirm_continuation_refined` 继续推进到：

- 参数：[v71_final_candidate_initial_confirm_continuation_short_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_continuation_short_refined_params.json)
- 执行：[v71_final_candidate_initial_confirm_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_execution.json)
- 结果目录：[initial_confirm_continuation_short_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_refined_validation_2020_2026_08_01)

这轮 same-basis 复核的关注点是：

1. short 初始腿收紧是否真的有净收益；
2. 它是否能继续抬升 `Sharpe / Calmar`；
3. 它是否保持住 `wzy` 当前的低回撤特征。

## 1. 全样本三分支结果

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy initial_confirm_continuation_short_refined` | `195.02%` | `0.9306` | `1.0459` | `-17.08%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

## 2. 相对上一版主候选

上一版 `continuation_refined`：

- `Sharpe = 0.9286`
- `Calmar = 1.0432`
- `Max DD = -17.08%`

当前版 `continuation_short_refined`：

- `Sharpe = 0.9306`
- `Calmar = 1.0459`
- `Max DD = -17.08%`

提升不大，但方向一致：

- 风报更高
- 留出段更稳
- 回撤没有恶化

## 3. 分层结果

### 训练段 `2020-2022`

- `Sharpe = 0.6267`
- `Calmar = 0.6466`

### 验证段 `2023-2024`

- `Sharpe = 1.3822`
- `Calmar = 2.3243`

### 留出段 `2025-2026_07`

- `Sharpe = 0.7018`
- `Calmar = 1.4636`

留出段继续略有改善，是这轮最重要的加分点。

## 4. 当前判断

这轮 short 侧优化说明了一件事：

- `wzy` 当前 short 不是整体要砍掉
- 而是只需要收紧 very early confirmed-short 初始腿

所以它是一条“结构校准”型优化，而不是方向反转。

## 5. 当前结论

**`initial_confirm_continuation_short_refined` 应当取代 `initial_confirm_continuation_refined`，成为当前 `wzy` 的正式三分支复核主候选。**

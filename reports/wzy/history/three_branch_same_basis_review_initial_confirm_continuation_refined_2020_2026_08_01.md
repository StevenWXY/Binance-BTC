# Three-Branch Same-Basis Review: Initial Confirm Continuation Refined

当前 `wzy` 主候选已经从 `initial_confirm_release_refined` 继续推进到：

- 参数：[v71_final_candidate_initial_confirm_continuation_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_continuation_refined_params.json)
- 执行：[v71_final_candidate_initial_confirm_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_execution.json)
- 结果目录：[initial_confirm_continuation_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_refined_validation_2020_2026_08_01)

这轮 same-basis 复核关注的是：

1. 新 continuation candidate 是否真的比 `release_refined` 更好；
2. 它在三分支横比里离 `main` 还有多远；
3. 它是否继续保住了 `wzy` 的低回撤特征。

## 1. 全样本三分支结果

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy initial_confirm_continuation_refined` | `194.28%` | `0.9286` | `1.0432` | `-17.08%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- `wzy` 继续稳定高于 `xuyujian`
- `wzy` 仍低于 `main`
- 但相较上一版 `release_refined`，`wzy` 已经更进一步接近 `main`

## 2. 相对 release_refined 的改善

上一版 `release_refined`：

- `Sharpe = 0.8572`
- `Calmar = 0.9253`
- `Max DD = -17.10%`

当前版 `continuation_refined`：

- `Sharpe = 0.9286`
- `Calmar = 1.0432`
- `Max DD = -17.08%`

这意味着：

- 风报继续抬升
- 回撤没有恶化
- 收益也同步增长

所以这不是“冒进换收益”，而是一次干净的主候选升级。

## 3. 分层结果

### 训练段 `2020-2022`

- `Sharpe = 0.6204`
- `Calmar = 0.6390`

### 验证段 `2023-2024`

- `Sharpe = 1.3842`
- `Calmar = 2.3287`

### 留出段 `2025-2026_07`

- `Sharpe = 0.6997`
- `Calmar = 1.4469`

留出段也同步改善，说明这次不是靠样本内挤出来的局部收益。

## 4. 当前判断

当前 `wzy` 已经进入这样一个阶段：

- 明显优于 `xuyujian_v71_ref`
- 与 `main_v43` 的差距继续缩小
- 在 `Max DD` 上继续保有优势

但如果目标是：

- `Sharpe` 超过 `main`
- `Calmar` 超过 `main`

那么还需要下一轮机制优化。

## 5. 当前结论

**`initial_confirm_continuation_refined` 应当取代 `initial_confirm_release_refined`，成为当前 `wzy` 的正式三分支复核主候选。**

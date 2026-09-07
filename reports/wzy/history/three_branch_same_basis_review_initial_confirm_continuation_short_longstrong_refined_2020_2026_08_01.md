# Three-Branch Same-Basis Review: Initial Confirm Continuation Short Longstrong Refined

> Historical note:
> 这份文档记录的是 `longstrong_refined` 阶段的正式 three-branch 复核。
> 它已经被 `tp_refined` 阶段取代，当前应优先阅读：
> [three_branch_same_basis_review_initial_confirm_continuation_short_longstrong_tp_refined_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/three_branch_same_basis_review_initial_confirm_continuation_short_longstrong_tp_refined_2020_2026_08_01.md)

当前 `wzy` 主候选已经从 `initial_confirm_continuation_short_longstrong` 继续推进到：

- 参数：[v71_final_candidate_initial_confirm_continuation_short_longstrong_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_continuation_short_longstrong_refined_params.json)
- 执行：[v71_final_candidate_initial_confirm_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_initial_confirm_execution.json)
- 结果目录：[initial_confirm_continuation_short_longstrong_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_refined_validation_2020_2026_08_01)

这轮 same-basis 复核关注的是：

1. refined 后的 strong-long protection 是否还能继续抬升风报；
2. 它是否进一步逼近 `main_v43`；
3. 它是否继续保持低回撤结构。

## 1. 全样本三分支结果

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `wzy initial_confirm_continuation_short_longstrong_refined` | `243.02%` | `1.0353` | `1.2003` | `-17.16%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- `wzy` 继续显著高于 `xuyujian`
- `wzy` 仍低于 `main`
- 但已经非常接近 `main`

## 2. 相对上一版主候选

上一版 `continuation_short_longstrong`：

- `Sharpe = 0.9765`
- `Calmar = 1.1149`
- `Max DD = -17.15%`

当前版 `continuation_short_longstrong_refined`：

- `Sharpe = 1.0353`
- `Calmar = 1.2003`
- `Max DD = -17.16%`

这次的形状是：

- 风报继续显著提高
- 收益继续明显提高
- 回撤几乎不变

这说明 refined 不是微小抖动，而是一次明确有效的参数中心更新。

## 3. 分层结果

### 训练段 `2020-2022`

- `Sharpe = 0.7725`
- `Calmar = 0.9330`

### 验证段 `2023-2024`

- `Sharpe = 1.4114`
- `Calmar = 2.3617`

### 留出段 `2025-2026_07`

- `Sharpe = 0.9070`
- `Calmar = 1.9702`

分层表现说明：

- 训练段大幅改善
- 验证段继续略增
- 留出段基本保持稳定

## 4. 当前判断

这轮 refine 说明：

- `long_strong_protection` 方向没有走到头
- 但它的有效区间很窄
- `0.9 / 0.88` 是当前更干净的中心点

所以这轮不是新机制，而是对当前最有效机制的精细化落点。

## 5. 当前结论

**`initial_confirm_continuation_short_longstrong_refined` 应当取代 `initial_confirm_continuation_short_longstrong`，成为当前 `wzy` 的正式三分支复核主候选。**

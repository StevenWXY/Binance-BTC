# WZY Current Documentation Guide

这份文档用于整理当前 `wzy` 主线相关报告，避免继续混用不同阶段的旧结论。

## 1. 当前主候选

当前 `wzy` 主候选为：

- 对外版本：`wzy_v72`
- 参数：[wzy_v72_tp_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/wzy_v72_tp_refined_params.json)
- 执行：[wzy_v72_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/wzy_v72_execution.json)

当前正式结论是：

- `wzy` 已经显著强于 `xuyujian_v71_ref`
- `wzy` 已经在 same-basis 口径下超过 `main_v43`
- 当前最强方向是 `wzy_v72 / initial_confirm_continuation_short_longstrong_tp_refined`

## 2. 当前应优先阅读的文档

### 2.1 当前主候选机制说明

- [initial_confirm_continuation_short_longstrong_tp_refined_review_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/initial_confirm_continuation_short_longstrong_tp_refined_review_2020_2026_08_01.md)

适合回答：

- 当前主候选机制是什么？
- 为什么 `first_fill_only` 没有成为主方向？
- 为什么 release 语义修正是这轮真正的增益来源？

### 2.2 当前三分支正式复核

- [three_branch_same_basis_review_initial_confirm_continuation_short_longstrong_tp_refined_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/three_branch_same_basis_review_initial_confirm_continuation_short_longstrong_tp_refined_2020_2026_08_01.md)

适合回答：

- 当前 `wzy` 在三分支里排什么位置？
- 是否已经超过 `xuyujian`？
- 距离 `main` 还有多大差距？

### 2.3 当前验证结果目录

- [initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01)

适合回答：

- same-basis 汇总指标是什么？
- 分层 `train / validation / holdout` 结果是什么？
- stress suite 聚合结果是什么？

## 3. 历史阶段文档

下面这些文档仍然保留，但现在应按“阶段记录”而不是“当前结论”来理解。

### 3.1 `initial_confirm` 第一阶段

- [initial_confirm_review_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/history/initial_confirm_review_2020_2026_08_01.md)

用途：

- 解释为什么主线从 `rebalanced` 转到 `initial_confirm`

### 3.2 更早的 `2023_targeted` 三分支阶段

- [three_branch_same_basis_live_like_review_2023_targeted_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/history/three_branch_same_basis_live_like_review_2023_targeted_2020_2026_08_01.md)

用途：

- 作为旧阶段复核的历史入口
- 不再代表当前主候选结论

## 4. 当前一句话总结

如果现在只保留一句当前状态，那就是：

**`initial_confirm_continuation_short_longstrong_tp_refined` 是当前唯一主候选；旧的 `2023_targeted`、第一阶段 `initial_confirm`、`release_refined`、`continuation_refined`、`continuation_short_refined`、`continuation_short_longstrong` 与 `continuation_short_longstrong_refined` 文档都应视为历史阶段记录，不再作为当前总结引用。**

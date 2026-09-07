# Initial Confirm Review (Historical Phase Note)

这份文档对应的是 `initial_confirm` 路线的**第一阶段结论**：

- 当时刚从 `rebalanced` 过渡到 `initial_confirm`
- 还没有补上 `initial_confirm` 的 release 强制 rebalance 语义
- 也还没有完成当前这轮 `release_refined` 的局部再收敛

因此，这份文档现在更适合作为：

- `initial_confirm` 路线为什么成立的历史说明
- 而不是当前主候选的最终结论文档

## 这份文档当时解决了什么问题

第一阶段 `initial_confirm` 的核心贡献是：

- 证明“低质量 `confirmed_long` 初始腿收紧”是有效方向
- 证明它比“亏损后再限制 reentry”更贴近问题本体
- 让 `wzy` 首次明显从 `rebalanced` 再向前迈了一步

也就是说，这份文档仍然有价值，因为它记录了当前主线为什么从：

- `rebalanced`
- `fast-fail cooldown`
- `execution reentry probe`

最终转向 `initial_confirm`

## 为什么它已被后续文档替代

当前主线已经继续往前推进了两步：

1. 补上 `initial_confirm` 的 release 语义
   - 缩放结束时强制 rebalance 回正常仓位

2. 在新语义下重新局部收敛
   - 得到 `initial_confirm_release_refined`

因此，当前更应采用的正式结论来自：

- [initial_confirm_release_refined_review_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/initial_confirm_release_refined_review_2020_2026_08_01.md)
- [three_branch_same_basis_review_initial_confirm_release_refined_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/three_branch_same_basis_review_initial_confirm_release_refined_2020_2026_08_01.md)

## 当前应该怎样理解这份文档

最合适的理解方式是：

- 它不是“当前主候选说明”
- 它是“当前主候选的前一阶段说明”

如果要追踪策略演化脉络，可以按这个顺序读：

1. 本文档：理解 `initial_confirm` 为什么取代 `rebalanced`
2. [initial_confirm_release_refined_review_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/initial_confirm_release_refined_review_2020_2026_08_01.md)：理解 release 修正为什么继续抬升同一路线
3. [three_branch_same_basis_review_initial_confirm_release_refined_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/three_branch_same_basis_review_initial_confirm_release_refined_2020_2026_08_01.md)：理解当前候选在三分支横比里的位置

## 当前状态一句话总结

`initial_confirm` 第一阶段是当前主线成立的起点；但真正应该被视为当前正式主候选的，是它后续演化出来的 `initial_confirm_release_refined`。

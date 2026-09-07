# Rebalanced Micro Tune And Cooldown Validation

本轮按要求做了两条线：

1. 基于 `rebalanced` 再做一轮很窄的 `target_vol / trend_scale` 微调
2. 回到 `fast-fail cooldown`，做一次更贴近 `2021` 的机制版本验证

结论先说：

- **当前 `rebalanced` 仍是局部最优，没有跑出比它更强的新参数版**
- **`fast-fail cooldown` 在真实数据下没有通过验证，暂时不值得启用进正式候选**

## 1. Rebalanced 附近的超窄微调

围绕当前主候选：

- `target_vol = 0.78`
- `trend_scale = 1.30`

只检查了最中心的几个邻点：

- `0.77 / 1.30`
- `0.78 / 1.29`
- `0.78 / 1.30`
- `0.78 / 1.31`
- `0.79 / 1.30`

### live-like 结果

| candidate | total_return | sharpe | calmar | max_drawdown |
|---|---:|---:|---:|---:|
| `0.78 / 1.30` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` |
| `0.78 / 1.31` | `116.85%` | `0.7333` | `0.6852` | `-18.21%` |
| `0.79 / 1.30` | `114.17%` | `0.7255` | `0.6753` | `-18.17%` |
| `0.78 / 1.29` | `109.24%` | `0.7190` | `0.6542` | `-18.14%` |
| `0.77 / 1.30` | `101.35%` | `0.6873` | `0.6173` | `-18.18%` |

### 观察

- 当前中心点 `0.78 / 1.30` 明显最好
- 往上提风险预算并不会继续改善
- 往下压风险预算也已经开始伤收益和风报
- 单独调高/调低 `trend_scale` 也都不如当前点

因此可以把当前判断写得更明确一点：

**`rebalanced` 在当前这片局部区域里已经是最优点。**

## 2. Fast-Fail Cooldown 的 2021 专项验证

这次专门围绕真实数据做了更贴近 `2021` 的验证，比较的版本有：

- baseline `rebalanced`
- `cool_12_4`
- `cool_12_6`
- `cool_16_4`
- `cool_16_6`

### 结果摘要

| candidate | total_return | sharpe | calmar | ret_2021 | ret_2023 | long_2021_pnl |
|---|---:|---:|---:|---:|---:|---:|
| baseline | `128.17%` | `0.7721` | `0.7807` | `-5.41%` | `70.55%` | `-1042.86` |
| `cool_12_6` | `97.01%` | `0.6637` | `0.6063` | `-5.41%` | `59.98%` | `-1036.35` |
| `cool_12_4` | `91.74%` | `0.6448` | `0.5802` | `-5.77%` | `56.08%` | `-1088.75` |
| `cool_16_4` | `91.88%` | `0.6449` | `0.5769` | `-5.81%` | `56.08%` | `-1096.28` |
| `cool_16_6` | `16.28%` | `0.2795` | `0.1212` | `-2.74%` | `5.63%` | `-347.44` |

### 观察

- `cool_12_6` 是这组里副作用最小的 cooldown 版本
- 但它对 `2021` 的改善几乎可以忽略：
  - `ret_2021`: `-5.41% -> -5.41%`
  - `long_2021_pnl`: `-1042.86 -> -1036.35`
- 同时它会显著伤害：
  - `2023`
  - 全样本 `Sharpe`
  - 全样本 `Calmar`
  - 全样本 `total_return`

更激进的 cooldown（如 `16 / 6`）虽然能明显减少 `2021 long` 损失，
但代价是把整个系统压得过于保守，连 `2023` 都几乎被砍坏。

因此这条机制线当前的结论很清楚：

**在现有实现下，`fast-fail cooldown` 还不是一个合格的正式候选机制。**

## 3. 当前结论

本轮没有产生新的正式候选，原因不是没做出变化，而是：

- 微调已经验证 `rebalanced` 就是当前局部最优
- `cooldown` 机制还没有通过“修 2021 且不伤 2023”的门槛

所以当前主候选保持不变：

- [v71_final_candidate_risk_adjusted_rebalanced_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_params.json)
- [v71_final_candidate_risk_adjusted_rebalanced_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_execution.json)

## 4. 下一步建议

既然这轮已经确认：

- 参数局部空间基本吃满
- 当前 cooldown 实现不够好

那后续更值得做的，不是继续在这两个方向上硬拧，而是：

1. 重新设计 `fast-fail cooldown` 的触发语义  
   例如只对 `long_probe / weak_long_quality` 类快速失败生效，而不是所有早期 long 退出都冷却。

2. 把 `cooldown` 做成“降级为 probe”而不是“直接不允许再入场”  
   这样更有机会修 `2021`，同时少伤 `2023`。

当前阶段的最佳结论是：

**保留 `rebalanced` 作为主候选，机制创新先继续研究，但不进入正式版本。**

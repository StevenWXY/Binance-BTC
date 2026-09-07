# 2023 定向优化复核

## 目标

围绕当前候选在 `2023` 年收益偏低的问题，识别是：

1. `long` 趋势参与不够  
2. `short` 错误暴露过多  
3. 持有/止损参数导致趋势单留不住

## 关键诊断

- `2023` 年 `long` 交易是赚钱的，`short` 交易是亏钱的。
- `trend_up` 的状态质量虽不算很强，但方向并没有错到不能做。
- `trend_down` 在 `2023` 的 6-bar 平均收益是正的，说明空头状态本身不干净。
- `long_continuation` 才是主要盈利来源，`short_release` 和部分 `short_probe` 在拖累。

## 扫描结果

结果目录：

- `reports/targeted_2023_optimization_2020_2026_08_01/`

最佳候选是 `short_lighter_scale`：

- 仅把 `short_scale: 0.12 -> 0.08`
- 同时把 `short_permission_scale: 1.00 -> 0.92`

## 新旧对比

旧版基线：`governor_reentry`

- Total Return: `23.01%`
- Sharpe: `0.3193`
- Calmar: `0.1815`
- Max DD: `-17.61%`

新版：`2023_targeted`

- Total Return: `37.73%`
- Sharpe: `0.4028`
- Calmar: `0.2914`
- Max DD: `-17.10%`

## 年度变化

- `2020`: `23.73% -> 24.26%`
- `2022`: `-2.64% -> -2.19%`
- `2023`: `1.90% -> 1.96%`
- `2024`: `-0.37% -> -0.14%`
- `2025`: `2.32% -> 9.86%`
- `2026`: `0.34% -> 3.49%`

## 解释

这轮优化最重要的结论不是“`2023` 自身被大幅抬高”，而是：

- 当前策略的主要短板之一确实是 `short` 暴露偏重
- 把 `short` 做得更轻以后，不仅 `2023` 略有改善，全样本 Sharpe / Calmar / 回撤也一起改善
- 这说明此前的“保守收益牺牲”并没有换来更好的风报；相反，较轻的 short 暴露更符合当前策略质量

## 推荐

当前推荐配置切换为：

- `configs/v71_final_candidate_2023_targeted_params.json`
- `configs/v71_final_candidate_2023_targeted_execution.json`

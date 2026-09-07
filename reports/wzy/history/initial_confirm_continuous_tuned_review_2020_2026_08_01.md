# Initial Confirm Continuous Tuned Review

这轮是在“连续缩放版 initial confirm”语义已经落地之后，围绕原主候选做一轮很窄的重新定中心。

目标不是大改机制，而是回答一个更具体的问题：

- 连续缩放本身是否有效？
- 如果有效，旧参数是否只是因为语义变化而偏重？

## 1. 候选

- 参数：`configs/v71_final_candidate_initial_confirm_continuous_params.json`
- 执行：`configs/v71_final_candidate_initial_confirm_execution.json`

核心参数相对旧 `initial_confirm` 主候选改为：

- `long_initial_confirm_bars = 3`
- `long_initial_confirm_scale = 0.80`
- `long_initial_confirm_quality_max = 0.62`

语义上等于：

- 仍然只处理 `confirmed_long`
- 仍然只处理趋势前 `3` 根 bar
- 但连续缩放只覆盖到更低质量区间
- 同时最差初始腿缩放也放松到 `80%`

## 2. 相对旧主候选的结果

旧主候选（硬阈值版 initial confirm）：

- `total_return = 144.53%`
- `Sharpe = 0.8122`
- `Calmar = 0.8463`
- `Max DD = -17.19%`

本轮 tuned continuous：

- `total_return = 144.76%`
- `Sharpe = 0.8188`
- `Calmar = 0.8405`
- `Max DD = -17.33%`

变化：

- `total_return`: `+0.23 pct`
- `Sharpe`: `+0.0066`
- `Calmar`: `-0.0059`
- `Max DD`: `-0.14 pct`

结论很直接：

- `Sharpe` 确实更高
- 总收益也略高
- 但 `Calmar` 没有跟上，回撤略变差

所以它更像一个 **Sharpe-first 的连续版备选候选**，还不够干净地替代当前主候选。

## 3. 分层结果

### 训练段 `2020-2022`

- 旧主候选：`Sharpe 0.5897 / Calmar 0.5763`
- tuned continuous：`Sharpe 0.5658 / Calmar 0.5440`

训练段略弱。

### 验证段 `2023-2024`

- 旧主候选：`Sharpe 1.2204 / Calmar 1.8907`
- tuned continuous：`Sharpe 1.2752 / Calmar 2.0102`

验证段明显更好，这说明连续缩放方向本身是成立的。

### 留出段 `2025-2026_07`

- 旧主候选：`Sharpe 0.4886 / Calmar 0.9854`
- tuned continuous：`Sharpe 0.4254 / Calmar 0.6814`

留出段明显转弱，这是当前不宜直接替换主候选的关键原因。

## 4. same-basis 三分支位置

- `main_v43`: `Sharpe 1.1053 / Calmar 1.3481`
- `wzy tuned continuous`: `Sharpe 0.8188 / Calmar 0.8405`
- `xuyujian_v71_ref`: `Sharpe 0.6294 / Calmar 0.4365`

这说明：

- tuned continuous 仍明显强于 `xuyujian`
- 相比旧 `wzy initial_confirm`，只是在内部做了一个“Sharpe 更高、Calmar 略弱”的权衡
- 与 `main` 的差距依旧主要在整体风报而不是单一年度爆发

## 5. stress validation

本轮已运行 `run_v71_candidate_validation.py` 自带 stress suite。

聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -10.12%`
- `worst_total_return = -5.45%`

说明连续版 tuned 候选在研究级 stress 下没有出现额外的稳定性问题。

## 6. 当前判断

这轮可以确认两件事：

1. 连续缩放不是坏方向。
   它在 `2023-2024` 这段确实比硬阈值版更顺。

2. 当前这组 tuned 参数还不适合直接替换旧主候选。
   因为用户更看重整体风报一致性，而不是只换来更高一点的 `Sharpe`。

## 7. 下一步更值得做的事

如果继续沿连续缩放往前推，更值得优先尝试的是：

1. 保持 `bars = 3` 不动，只继续微调 `scale / quality_max`
   目标是保住验证段优势，同时把 `2025-2026` 留出段拉回去。

2. 让连续缩放只作用于更早的 first fill，而不是整个初始腿窗口
   这样有机会保留 `2023-2024` 的过滤收益，同时减少对留出段恢复期的拖累。

当前阶段更稳妥的结论是：

**保留旧 `initial_confirm` 作为主候选，新增 tuned continuous 作为研究备选。**

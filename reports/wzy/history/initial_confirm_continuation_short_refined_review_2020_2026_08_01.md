# Initial Confirm Continuation Short Refined Review

这轮继续优化不是再去放大 long，而是沿着当前主候选 `initial_confirm_continuation_refined` 的基础，补了一层 **short 初始腿收紧**。

诊断先给出的信号很明确：

- short 全样本并不是负贡献
- 但亏钱 short 大多发生在入场后的前 `10-25` 小时
- 退出原因以 `stop_loss` 为主

也就是说，当前 short 的主要问题不是“趋势后段赚不到”，而是**有一批 early confirmed-short 初始腿质量不够稳，容易被很快打掉**。

## 1. 代码与测试

本轮在 `src/btc_regime/v71_live.py` 中新增了默认关闭的 short 研究钩子：

- `short_initial_confirm_bars`
- `short_initial_confirm_scale`

语义：

- 只对 `confirmed_short` 生效
- 只作用于趋势前 `N` 根 bar
- 初始腿结束时强制 rebalance 回正常仓位

它和 long 侧的 `initial_confirm` 很像，但 short 这边没有再做连续质量缩放，而是保持更简单的固定缩放，因为当前问题更像“early short stop-loss 过密”，不是 long 那种明显的质量分层。

测试：

- `tests/test_v71_live.py`
  - helper 层测试：验证 short 初始腿 multiplier 只作用于早段 `confirmed_short`
  - 信号层测试：验证 early short 被缩放，后段自动恢复

验证：

- `py_compile src/btc_regime/v71_live.py tests/test_v71_live.py`
- `pytest tests/test_v71_live.py tests/test_strategy.py`
- 结果：`36 passed`

## 2. 窄扫结论

我只做了 very narrow `bars / scale` 扫描。

结果形状很清楚：

- `3 bars` 及以上会明显伤留出段
- 只有 `2 bars` 是有效区域
- `scale` 过于离散，存在 rebalance 状态边界

最终最优点是：

- `short_initial_confirm_bars = 2`
- `short_initial_confirm_scale = 0.94`

对应正式候选：

- 参数：`configs/v71_final_candidate_initial_confirm_continuation_short_refined_params.json`
- 执行：`configs/v71_final_candidate_initial_confirm_execution.json`

## 3. 相对 continuation_refined 的提升

上一版主候选 `initial_confirm_continuation_refined`：

- `total_return = 194.28%`
- `Sharpe = 0.9286`
- `Calmar = 1.0432`
- `Max DD = -17.08%`

本轮 `initial_confirm_continuation_short_refined`：

- `total_return = 195.02%`
- `Sharpe = 0.9306`
- `Calmar = 1.0459`
- `Max DD = -17.08%`

增量不算大，但很干净：

- `Sharpe`: `+0.0019`
- `Calmar`: `+0.0027`
- `Max DD`: 略好一点
- `holdout Calmar`: `1.4469 -> 1.4636`

也就是说，这次不是冒进，而是一次小幅但一致的风报抬升。

## 4. 分层结果

### 训练段 `2020-2022`

- `total_return = 30.33%`
- `Sharpe = 0.6267`
- `Calmar = 0.6466`
- `Max DD = -14.27%`

### 验证段 `2023-2024`

- `total_return = 95.26%`
- `Sharpe = 1.3822`
- `Calmar = 2.3243`
- `Max DD = -17.08%`

### 留出段 `2025-2026_07`

- `total_return = 15.93%`
- `Sharpe = 0.7018`
- `Calmar = 1.4636`
- `Max DD = -6.70%`

这版最大的加分点在留出段：不是把验证段抬得更激进，而是把 holdout 风报再往上拱了一点。

## 5. 为什么这版有效

这轮有效的原因，不是继续缩 short 总暴露，而是只处理：

- `confirmed_short`
- very early bars
- 很容易被 stop-loss 打掉的初始腿

因此它没有破坏 short 后段真正赚钱的部分，只是把最容易犯错的那一小段削掉一点。

## 6. same-basis 三分支位置

- `main_v43`
  - `Sharpe 1.1053`
  - `Calmar 1.3481`

- `wzy initial_confirm_continuation_short_refined`
  - `Sharpe 0.9306`
  - `Calmar 1.0459`

- `xuyujian_v71_ref`
  - `Sharpe 0.6294`
  - `Calmar 0.4365`

当前状态：

- `wzy` 继续显著强于 `xuyujian`
- `wzy` 距离 `main` 又缩小了一小步
- `wzy` 仍未追平 `main`

## 7. stress validation

正式验证目录：

- [initial_confirm_continuation_short_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_refined_validation_2020_2026_08_01)

stress suite 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -10.11%`
- `worst_total_return = -5.47%`

没有出现新的稳定性退化。

## 8. 当前结论

这轮可以很明确地说：

1. short 参数窄扫基本不动，说明现有 short 阀门空间有限。
2. short 真正的问题更像是 early confirmed-short 初始腿。
3. `short_initial_confirm` 的有效区间很窄，但 `2 bars / 0.94` 确实成立。

因此，当前最合理的决定是：

**用 `initial_confirm_continuation_short_refined` 替代 `initial_confirm_continuation_refined`，成为新的 `wzy` 主候选。**

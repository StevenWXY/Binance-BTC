# Initial Confirm Continuation Refined Review

这轮继续优化沿着 `initial_confirm_release_refined` 的主线往前推，但不再继续压 early long，而是只给 **高质量 confirmed-long continuation** 一个很克制的增仓钩子。

核心思路是：

- early `confirmed_long` 仍沿用 `initial_confirm` 的收紧逻辑
- 只有当趋势持续到更后段，并且 `trend_quality_score` 与 `tradability_score` 同时达到高阈值时
- 才允许一个很小的 `continuation add-on`

这相当于把 “保守开头” 和 “证据累积后再加仓” 组合到同一条 long 路线上。

## 1. 代码与测试

本轮新增的研究钩子都在 `src/btc_regime/v71_live.py`，默认关闭：

- `long_continuation_add_on_min_bars`
- `long_continuation_add_on_confirm_bars`
- `long_continuation_add_on_scale`
- `long_continuation_add_on_quality_min`
- `long_continuation_add_on_tradability_min`

语义：

- 只对 `confirmed_long` 生效
- 只在趋势年龄达到 `min_bars` 之后才开始考虑
- 只有当质量/可交易性连续满足阈值 `confirm_bars` 根之后，才激活 add-on
- add-on 释放时同样强制 rebalance，避免旧仓位挂住

测试：

- `tests/test_v71_live.py`
  - helper 层测试：验证需要连续证据和阈值同时满足
  - 信号层测试：验证 add-on 只放大后段 confirmed-long

验证：

- `py_compile src/btc_regime/v71_live.py tests/test_v71_live.py`
- `pytest tests/test_v71_live.py tests/test_strategy.py`
- 结果：`34 passed`

## 2. 窄扫结论

这轮没有大范围扫参数，只做了 very narrow continuation add-on 测试。

大部分点都会让 `Sharpe / Calmar` 回落，说明：

- continuation add-on 不能打宽
- 不能太早
- 也不能给太大的 scale

最后跑出来的最优点是：

- `long_continuation_add_on_min_bars = 8`
- `long_continuation_add_on_confirm_bars = 2`
- `long_continuation_add_on_scale = 1.04`
- `long_continuation_add_on_quality_min = 0.84`
- `long_continuation_add_on_tradability_min = 0.84`

对应正式候选：

- 参数：`configs/v71_final_candidate_initial_confirm_continuation_refined_params.json`
- 执行：`configs/v71_final_candidate_initial_confirm_execution.json`

## 3. 相对 release_refined 的提升

上一版主候选 `initial_confirm_release_refined`：

- `total_return = 163.03%`
- `Sharpe = 0.8572`
- `Calmar = 0.9253`
- `Max DD = -17.10%`

本轮 `initial_confirm_continuation_refined`：

- `total_return = 194.28%`
- `Sharpe = 0.9286`
- `Calmar = 1.0432`
- `Max DD = -17.08%`

增量：

- `total_return`: `+31.25 pct`
- `Sharpe`: `+0.0714`
- `Calmar`: `+0.1178`
- `Max DD`: 略好一点

也就是说，这次不是“多赚一点但风报变差”，而是：

**收益、Sharpe、Calmar、Max DD 一起改善。**

## 4. 分层结果

### 训练段 `2020-2022`

- `total_return = 29.92%`
- `Sharpe = 0.6204`
- `Calmar = 0.6390`
- `Max DD = -14.27%`

### 验证段 `2023-2024`

- `total_return = 95.48%`
- `Sharpe = 1.3842`
- `Calmar = 2.3287`
- `Max DD = -17.08%`

### 留出段 `2025-2026_07`

- `total_return = 15.87%`
- `Sharpe = 0.6997`
- `Calmar = 1.4469`
- `Max DD = -6.75%`

留出段也同步抬升，没有出现“训练/验证更好、留出更差”的情况。

## 5. 为什么这版有效

这轮的关键不是单纯把 long 仓位放大，而是把增仓限制在：

- 更晚的 continuation 阶段
- 更高的质量阈值
- 更高的 tradability 阈值
- 更小的 scale

因此它更像：

- 不在早段冒进
- 只在“已经走出来”的趋势里补一点点参与度

这与之前失败的宽 continuation add-on 有本质区别。

## 6. same-basis 三分支位置

- `main_v43`
  - `Sharpe 1.1053`
  - `Calmar 1.3481`

- `wzy initial_confirm_continuation_refined`
  - `Sharpe 0.9286`
  - `Calmar 1.0432`

- `xuyujian_v71_ref`
  - `Sharpe 0.6294`
  - `Calmar 0.4365`

当前状态：

- `wzy` 继续显著强于 `xuyujian`
- `wzy` 距离 `main` 进一步缩小差距
- 但还没有追平 `main`

## 7. stress validation

正式验证目录：

- [initial_confirm_continuation_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_refined_validation_2020_2026_08_01)

stress suite 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -10.10%`
- `worst_total_return = -5.47%`

没有看到新的稳定性退化。

## 8. 当前结论

这轮可以明确给出结论：

1. 宽 continuation add-on 会伤 `Sharpe / Calmar`。
2. 只有“更晚、更窄、更高质量”的 continuation add-on 才成立。
3. `initial_confirm_continuation_refined` 已经跑赢当前 `release_refined` 主候选。

因此，当前最合理的决定是：

**用 `initial_confirm_continuation_refined` 替代 `initial_confirm_release_refined`，成为新的 `wzy` 主候选。**

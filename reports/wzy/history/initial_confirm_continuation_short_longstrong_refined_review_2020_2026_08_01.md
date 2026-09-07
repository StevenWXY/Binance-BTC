# Initial Confirm Continuation Short Longstrong Refined Review

> Historical note:
> 这份文档记录的是 `longstrong_refined` 阶段的机制说明。
> 它已经被 `tp_refined` 阶段取代，当前应优先阅读：
> [initial_confirm_continuation_short_longstrong_tp_refined_review_2020_2026_08_01.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/current/initial_confirm_continuation_short_longstrong_tp_refined_review_2020_2026_08_01.md)

这轮继续优化没有再引入新的大机制，而是沿着已经证明有效的 `long_strong_protection` 继续做 very narrow refine。

上一版我们已经确认：

- 高质量 `confirmed_long` 的 protection width 放宽，确实能抬升 `Sharpe / Calmar`
- `long_take_profit_extension` 这条线不打结果，可以保留钩子但不进主线

所以这一轮的目标很明确：

- 不再横向扩机制
- 只把 `long_strong_protection` 的有效区间再吃深一点

## 1. 代码与测试

代码层没有新增新的机制类型，仍然沿用：

- `long_strong_protection_atr_bonus`
- `long_strong_protection_quality_min`
- `long_strong_protection_tradability_min`

本轮只是继续细化这个机制的参数中心。

测试没有新增失败项，仍然保持：

- `py_compile src/btc_regime/v71_live.py tests/test_v71_live.py`
- `pytest tests/test_v71_live.py tests/test_strategy.py`
- 结果：`40 passed`

## 2. refine 结论

我围绕上一版最优点：

- `bonus = 0.7`
- `threshold = 0.84`

做了一轮 very narrow refine。

主要结果：

- `0.7 / 0.84~0.88` 基本都稳定
- `0.9` 明显更强
- `0.9 / 0.88` 是当前最优点

对应正式候选：

- 参数：`configs/v71_final_candidate_initial_confirm_continuation_short_longstrong_refined_params.json`
- 执行：`configs/v71_final_candidate_initial_confirm_execution.json`

关键参数变为：

- `long_strong_protection_atr_bonus = 0.9`
- `long_strong_protection_quality_min = 0.88`
- `long_strong_protection_tradability_min = 0.88`

## 3. 相对上一版主候选的提升

上一版 `initial_confirm_continuation_short_longstrong`：

- `total_return = 216.40%`
- `Sharpe = 0.9765`
- `Calmar = 1.1149`
- `Max DD = -17.15%`

本轮 `initial_confirm_continuation_short_longstrong_refined`：

- `total_return = 243.02%`
- `Sharpe = 1.0353`
- `Calmar = 1.2003`
- `Max DD = -17.16%`

增量：

- `total_return`: `+26.62 pct`
- `Sharpe`: `+0.0588`
- `Calmar`: `+0.0854`
- `Max DD`: 基本持平，仅略差 `0.01 pct`

这次的形状非常好：

- 收益继续明显抬升
- `Sharpe` 正式推过 `1.03`
- `Calmar` 也同步抬升
- 回撤几乎没有额外代价

## 4. 分层结果

### 训练段 `2020-2022`

- `total_return = 40.50%`
- `Sharpe = 0.7725`
- `Calmar = 0.9330`
- `Max DD = -12.86%`

### 验证段 `2023-2024`

- `total_return = 97.57%`
- `Sharpe = 1.4114`
- `Calmar = 2.3617`
- `Max DD = -17.16%`

### 留出段 `2025-2026_07`

- `total_return = 23.58%`
- `Sharpe = 0.9070`
- `Calmar = 1.9702`
- `Max DD = -7.28%`

这轮最值得注意的是：

- 训练段显著修复
- 验证段继续略增
- 留出段基本稳住，没有被明显打坏

也就是说，这一版不是靠某个单独年份“挤”出来的。

## 5. 为什么 refine 还能继续有效

这说明上一版 `long_strong_protection` 的方向完全正确，但 `0.7 / 0.84` 还不是极限点。

把强 long 的保护再放宽一点，并且把阈值再抬高一点，有两个效果同时发生：

- 更少干扰 medium-quality long
- 更集中地保护 very strong continuation long

这正好符合我们前面的诊断：

- 当前 `wzy` 的核心问题不是 broad long participation 不够
- 而是顶级 strong long continuation 仍然会被保护层打断得偏早

## 6. same-basis 三分支位置

- `main_v43`
  - `Sharpe 1.1053`
  - `Calmar 1.3481`

- `wzy initial_confirm_continuation_short_longstrong_refined`
  - `Sharpe 1.0353`
  - `Calmar 1.2003`

- `xuyujian_v71_ref`
  - `Sharpe 0.6294`
  - `Calmar 0.4365`

当前状态：

- `wzy` 显著强于 `xuyujian`
- `wzy` 已经非常接近 `main`
- 但 `Sharpe / Calmar` 仍未超过 `main`

## 7. stress validation

正式验证目录：

- [initial_confirm_continuation_short_longstrong_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_refined_validation_2020_2026_08_01)

stress suite 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -10.11%`
- `worst_total_return = -5.63%`

没有出现新的稳定性恶化。

## 8. 当前结论

这轮可以明确给出结论：

1. `long_strong_protection` 是当前最有效的继续优化方向。
2. 在这个方向上，`0.9 / 0.88` 比上一版 `0.7 / 0.84` 更优。
3. `initial_confirm_continuation_short_longstrong_refined` 已经显著跑赢上一版 `longstrong`。

因此，当前最合理的决定是：

**用 `initial_confirm_continuation_short_longstrong_refined` 替代 `initial_confirm_continuation_short_longstrong`，成为新的 `wzy` 主候选。**

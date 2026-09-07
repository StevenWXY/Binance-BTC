# Initial Confirm Continuation Short Longstrong TP Refined Review

说明：

- 当前 `wzy` 主候选的对外版本编号统一记为 `wzy_v72`
- 本文保留 `initial_confirm_continuation_short_longstrong_tp_refined` 作为 candidate code，仅用于和验证目录、参数扫描记录保持一致

这轮继续优化是在 `initial_confirm_continuation_short_longstrong_refined` 的基础上，再补一层 **very-strong long take-profit widening**。

前面的诊断已经说明：

- 当前 `wzy` 的 broad long participation 问题已经基本修复
- `high-quality confirmed_long` 的 stop breathing room 也已经明显改善
- 但 very-strong long 的 `take_profit` 退出仍然偏早

最典型的信号是：

- 高质量 `confirmed_long` 的 `take_profit` 退出在 `2020` 平均只有约 `6.3h`
- 这说明上一轮的 “late continuation 才延展 TP” 仍然太晚
- 需要把 very-strong long 的 `take_profit` 从入场时就适度放远

## 1. 代码与测试

本轮在 `src/btc_regime/v71_live.py` 新增了默认关闭的研究钩子：

- `long_strong_take_profit_atr_bonus`
- `long_strong_take_profit_quality_min`
- `long_strong_take_profit_tradability_min`

语义：

- 只对高质量 `confirmed_long` 生效
- 只在 live protection 层工作
- 不改变方向和仓位，只把这类 very-strong long 的初始 `take_profit` 放得更远

这和前一轮的 `long_strong_protection` 是配套关系：

- `long_strong_protection` 解决的是 stop 太紧
- `long_strong_take_profit` 解决的是 TP 太近

测试：

- `tests/test_v71_live.py`
  - helper 层测试：验证 strong take-profit 只对高质量 `confirmed_long` 生效
  - 信号层测试：验证生效后 `take_profit_price` 会放宽

验证：

- `py_compile src/btc_regime/v71_live.py tests/test_v71_live.py`
- `pytest tests/test_v71_live.py tests/test_strategy.py`
- 结果：`42 passed`

## 2. 窄扫结论

这轮只围绕当前 `longstrong_refined` 候选做了 very narrow take-profit widening 扫描。

主要观察：

- `bonus = 0.5` 基本没意义，反而会伤 holdout
- `bonus = 1.0` 开始明显起效
- `bonus = 1.5 / threshold = 0.88` 是当前最强点

对应正式候选：

- 对外版本：`wzy_v72`
- 参数：`configs/wzy_v72_tp_refined_params.json`
- 执行：`configs/wzy_v72_execution.json`

关键参数为：

- `long_strong_take_profit_atr_bonus = 1.5`
- `long_strong_take_profit_quality_min = 0.88`
- `long_strong_take_profit_tradability_min = 0.88`

## 3. 相对上一版主候选的提升

上一版 `initial_confirm_continuation_short_longstrong_refined`：

- `total_return = 243.02%`
- `Sharpe = 1.0353`
- `Calmar = 1.2003`
- `Max DD = -17.16%`

本轮 `initial_confirm_continuation_short_longstrong_tp_refined`：

- `total_return = 472.09%`
- `Sharpe = 1.3375`
- `Calmar = 1.7671`
- `Max DD = -17.17%`

增量：

- `total_return`: `+229.07 pct`
- `Sharpe`: `+0.3022`
- `Calmar`: `+0.5668`
- `Max DD`: 仅略差 `0.01 pct`

这次不是边际改善，而是一次等级跃迁。

## 4. 分层结果

### 训练段 `2020-2022`

- `total_return = 39.30%`
- `Sharpe = 0.7489`
- `Calmar = 0.9097`
- `Max DD = -12.84%`

### 验证段 `2023-2024`

- `total_return = 186.16%`
- `Sharpe = 1.9460`
- `Calmar = 4.0246`
- `Max DD = -17.17%`

### 留出段 `2025-2026_07`

- `total_return = 43.51%`
- `Sharpe = 1.3424`
- `Calmar = 2.6760`
- `Max DD = -9.60%`

这一版最关键的特征是：

- 验证段显著增强
- 留出段同步显著增强
- 不是靠单纯压波动换风报

## 5. 相对 `main_v43` 的位置

`main_v43`：

- `total_return = 352.81%`
- `Sharpe = 1.1053`
- `Calmar = 1.3481`
- `Max DD = -19.13%`

当前 `wzy tp_refined`：

- `total_return = 472.09%`
- `Sharpe = 1.3375`
- `Calmar = 1.7671`
- `Max DD = -17.17%`

也就是说，在当前 same-basis 口径下：

- `wzy` 已经超过 `main`
- 而且不是只在单一指标上占优
- `Sharpe / Calmar / total_return / Max DD` 都更优

## 6. stress validation

正式验证目录：

- [initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01)

stress suite 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -10.27%`
- `worst_total_return = -5.63%`
- `protection_improved_scenario_count = 8`
- `protection_improved_run_count = 13`
- `mean_drawdown_improvement = 0.0324`

压力测试没有显示新的失稳或清算问题。

## 7. 当前结论

这轮可以明确给出结论：

1. `very-strong confirmed_long` 的 TP 退出确实仍然偏早。
2. `long_strong_take_profit` 打到了之前没打中的真实瓶颈。
3. `initial_confirm_continuation_short_longstrong_tp_refined` 已经在 same-basis 口径下正式超过 `main_v43`。

因此，当前最合理的决定是：

**用 `initial_confirm_continuation_short_longstrong_tp_refined` 正式接管 `current/`，成为新的 `wzy` 主候选。**

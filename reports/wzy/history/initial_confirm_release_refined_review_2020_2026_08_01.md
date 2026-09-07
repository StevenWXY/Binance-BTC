# Initial Confirm Release Refined Review

这轮继续优化没有再去扩机制，而是先把一个语义缺口补完整：

- `initial_confirm` 开始缩放时，会强制 rebalance
- 但缩放结束时，如果仓位变化不足 `min_rebalance_delta`，旧的缩仓位可能会被多挂几根 bar

这和“只在 early confirmed-long 初始腿收紧”的原始意图并不完全一致。

所以这轮的核心不是新发明，而是把 `initial_confirm` 的 **release 语义** 补齐：

- 当 `initial_confirm_multiplier` 从 `< 1.0` 回到 `1.0` 时
- 同样强制触发 rebalance

## 1. 代码与测试

本轮落地内容：

- `src/btc_regime/v71_live.py`
  - 增加 `long_initial_confirm_first_fill_only` 研究开关，默认关闭
  - 新增 `initial_confirm_release` 强制 rebalance 逻辑
  - 用 `initial_confirm_multipliers` 显式跟踪上一根 bar 的实际缩放状态

- `tests/test_v71_live.py`
  - 增加 helper 层测试，验证 `first_fill_only` 只打第一次 confirmed fill
  - 增加信号层测试，验证 first-fill-only 会在第二根 confirmed bar 恢复到正常仓位

验证：

- `py_compile src/btc_regime/v71_live.py tests/test_v71_live.py`
- `pytest tests/test_v71_live.py tests/test_strategy.py`
- 结果：`32 passed`

## 2. first-fill-only 结论

我先用上轮 continuous tuned 的中心点做了 first-fill-only 验证：

- 参数：`configs/v71_final_candidate_initial_confirm_first_fill_params.json`
- 结果：
  - `total_return = 129.07%`
  - `Sharpe = 0.7754`
  - `Calmar = 0.7851`
  - `Max DD = -17.09%`

它没有跑赢当前主候选，尤其留出段明显转弱：

- `holdout_2025_2026_07`
  - `Sharpe 0.1264`
  - `Calmar 0.0996`

因此：

**first-fill-only 作为当前主方向不成立。**

## 3. 真正有效的提升来自 release 修正

把 release 语义补上之后，原 `initial_confirm` 主候选本身被明显抬升：

- recheck 参数：`configs/v71_final_candidate_initial_confirm_params.json`
- recheck 结果：
  - `total_return = 162.81%`
  - `Sharpe = 0.8566`
  - `Calmar = 0.9244`
  - `Max DD = -17.11%`

这个结果比之前同名候选明显更强，说明前面的主要缺口不是参数，而是仓位释放语义。

## 4. release 语义下的局部窄扫

围绕 recheck 结果，我只做了一轮很窄的 `scale / quality_max` 局部扫描。

最优点是：

- `long_initial_confirm_scale = 0.78`
- `long_initial_confirm_quality_max = 0.70`

对应正式候选：

- 参数：`configs/v71_final_candidate_initial_confirm_release_refined_params.json`
- 执行：`configs/v71_final_candidate_initial_confirm_execution.json`

## 5. refined 结果

### 全样本 `2020-2026_07`

- `total_return = 163.03%`
- `Sharpe = 0.8572`
- `Calmar = 0.9253`
- `Max DD = -17.10%`

相对 recheck：

- `total_return`: `+0.22 pct`
- `Sharpe`: `+0.0006`
- `Calmar`: `+0.0009`
- `Max DD`: 基本持平，略好一点

### 训练段 `2020-2022`

- `Sharpe = 0.5505`
- `Calmar = 0.5327`

### 验证段 `2023-2024`

- `Sharpe = 1.3004`
- `Calmar = 2.0980`

### 留出段 `2025-2026_07`

- `Sharpe = 0.6376`
- `Calmar = 1.1724`

也就是说，它不是只靠训练段或验证段抬起来，而是留出段同样有改善。

## 6. same-basis 三分支位置

- `main_v43`
  - `Sharpe 1.1053`
  - `Calmar 1.3481`

- `wzy initial_confirm_release_refined`
  - `Sharpe 0.8572`
  - `Calmar 0.9253`

- `xuyujian_v71_ref`
  - `Sharpe 0.6294`
  - `Calmar 0.4365`

这轮之后：

- `wzy` 继续稳定高于 `xuyujian`
- 相比 `main` 仍有差距
- 但风报和收益都比之前的 `wzy initial_confirm` 又靠前了一步

## 7. stress validation

`run_v71_candidate_validation.py` 自带 stress suite 结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -9.98%`
- `worst_total_return = -5.47%`

没有看到新的稳定性退化。

## 8. 当前结论

这轮可以给出一个很明确的判断：

1. `first_fill_only` 不是当前最优方向。
2. 真正的收益来自把 `initial_confirm` 的 release 语义补全。
3. 在新语义下，`0.78 / 0.70 / 3 bars` 是当前最优局部点。

因此当前最合理的决定是：

**用 `initial_confirm_release_refined` 替代现有主候选。**

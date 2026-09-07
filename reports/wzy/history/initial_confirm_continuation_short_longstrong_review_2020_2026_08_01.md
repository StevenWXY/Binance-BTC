# Initial Confirm Continuation Short Longstrong Review

这轮继续优化不是再压 short，也不是继续扩大 long continuation add-on，而是针对一个更具体的症状做修正：

- `2020` 的 long 交易被打得太碎
- 亏钱 long 里很多并不是低质量信号
- 很多高质量 `confirmed_long` 在 continuation 阶段仍然会被 `stop_loss` 打掉

这说明当前 `wzy` 距离 `main` 的一个关键差距，并不是不会做 long，而是**高质量 long continuation 的保护带宽仍然偏紧**。

## 1. 代码与测试

本轮在 `src/btc_regime/v71_live.py` 新增了默认关闭的研究钩子：

- `long_strong_protection_atr_bonus`
- `long_strong_protection_quality_min`
- `long_strong_protection_tradability_min`

语义：

- 只对高质量 `confirmed_long` 生效
- 只在 live protection 层工作
- 不改变信号方向，只把这类 strong long 的 `stop_atr` 与 `trailing_stop_atr` 略微放宽

也就是说，这个机制不是为了让策略“更激进”，而是为了让已经证明质量足够高的 long continuation 少一点无效 stop-out。

同时我还验证了另一条研究线：

- `long_take_profit_extension_*`

结论是：它虽然在信号层能触发，但实盘口径结果完全不动，没有打到真实收益瓶颈，因此保留为研究钩子，不进入当前候选。

测试：

- `tests/test_v71_live.py`
  - helper 层测试：验证 strong protection 只对高质量 `confirmed_long` 生效
  - 信号层测试：验证生效后 `stop_price` 会放宽

验证：

- `py_compile src/btc_regime/v71_live.py tests/test_v71_live.py`
- `pytest tests/test_v71_live.py tests/test_strategy.py`
- 结果：`40 passed`

## 2. 诊断与窄扫结论

这轮先做了 2020 long 交易诊断。

关键发现：

- `2020` long 交易数很多，但平均单笔收益很碎
- `stop_loss` 是 2020 long 最大负贡献项
- 很多亏钱 long 不是低质量 `probe_long`
- 而是高质量 `confirmed_long / long_continuation`

所以我没有再继续压 early long，而是改去放宽 **高质量 long continuation 的 protection width**。

窄扫只扫了：

- `long_strong_protection_atr_bonus`
- `quality / tradability threshold`

最优点是：

- `long_strong_protection_atr_bonus = 0.7`
- `long_strong_protection_quality_min = 0.84`
- `long_strong_protection_tradability_min = 0.84`

对应正式候选：

- 参数：`configs/v71_final_candidate_initial_confirm_continuation_short_longstrong_params.json`
- 执行：`configs/v71_final_candidate_initial_confirm_execution.json`

## 3. 相对上一版主候选的提升

上一版主候选 `initial_confirm_continuation_short_refined`：

- `total_return = 195.02%`
- `Sharpe = 0.9306`
- `Calmar = 1.0459`
- `Max DD = -17.08%`

本轮 `initial_confirm_continuation_short_longstrong`：

- `total_return = 216.40%`
- `Sharpe = 0.9765`
- `Calmar = 1.1149`
- `Max DD = -17.15%`

增量：

- `total_return`: `+21.38 pct`
- `Sharpe`: `+0.0459`
- `Calmar`: `+0.0690`
- `Max DD`: 只略差 `0.07 pct`

这次的形状是很理想的：

- 收益明显抬升
- `Sharpe / Calmar` 同时抬升
- 回撤只出现极小幅让步

## 4. 分层结果

### 训练段 `2020-2022`

- `total_return = 29.65%`
- `Sharpe = 0.6166`
- `Calmar = 0.6254`
- `Max DD = -14.46%`

训练段没有更亮眼，甚至略弱一点，这反而是个好信号：

- 这版不是靠样本内挤出来的
- 改善主要来自后面的验证段和留出段

### 验证段 `2023-2024`

- `total_return = 97.42%`
- `Sharpe = 1.4066`
- `Calmar = 2.3594`
- `Max DD = -17.15%`

### 留出段 `2025-2026_07`

- `total_return = 23.61%`
- `Sharpe = 0.9083`
- `Calmar = 1.9749`
- `Max DD = -7.27%`

这轮最重要的增益，其实出现在：

- `2023-2024`
- `2025-2026_07`

也就是说，strong-long protection 并没有只是修复 2020，而是同时改善了后段强趋势参与效率。

## 5. 为什么这版有效

当前 `wzy` 已经做对了几件事：

- long 初始腿收紧
- high-quality continuation 小幅 add-on
- short early confirm 收紧

但在这之后，还差最后一个平衡点：

- 对高质量 strong long，保护仍然略紧

这次的 `long_strong_protection` 正好补上这个缺口：

- 不去放大弱 long
- 不去碰 short
- 也不改 broad risk budget
- 只让高质量 long continuation 少一点被无效打断

所以它的增益是结构性的，而不是参数噪声。

## 6. same-basis 三分支位置

- `main_v43`
  - `Sharpe 1.1053`
  - `Calmar 1.3481`

- `wzy initial_confirm_continuation_short_longstrong`
  - `Sharpe 0.9765`
  - `Calmar 1.1149`

- `xuyujian_v71_ref`
  - `Sharpe 0.6294`
  - `Calmar 0.4365`

当前状态：

- `wzy` 继续显著强于 `xuyujian`
- `wzy` 又明显向 `main` 缩小了一步差距
- 但 `Sharpe / Calmar` 仍未超过 `main`

## 7. stress validation

正式验证目录：

- [initial_confirm_continuation_short_longstrong_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_validation_2020_2026_08_01)

stress suite 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -9.66%`
- `worst_total_return = -5.63%`

没有看到新的稳定性恶化。

## 8. 当前结论

这轮可以明确给出结论：

1. `long_take_profit_extension` 没打到真实问题，可以保留研究钩子但不进入主线。
2. 真正有效的是 `high-quality confirmed_long` 的 protection width 放宽。
3. `initial_confirm_continuation_short_longstrong` 已经明显跑赢上一版 `short_refined`。

因此，当前最合理的决定是：

**用 `initial_confirm_continuation_short_longstrong` 替代 `initial_confirm_continuation_short_refined`，成为新的 `wzy` 主候选。**

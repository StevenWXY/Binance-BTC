# Fast-Fail Probe Cooldown Validation

这轮继续优化的目标，是把上一版 `fast-fail cooldown` 从：

- “直接挡掉下一次 long 再入场”

改成：

- “下一次 long 仍允许入场，但只能降级为 probe”

这样做的出发点是：

- 试图修 `2021` 里的 long 假突破与早期失败
- 同时避免把 `2023` 这种强趋势年一起砍坏

## 1. 代码改动

本轮对 `v71_live.py` 做了两处关键改动：

1. 冷却期不再阻止 `trend_up` 状态建立
2. 冷却期内的 long permission 会被降级为 `cooldown_probe_long`

并新增一个默认关闭的研究参数：

- `long_fast_fail_probe_scale`

其作用是：

- 冷却期内 long 信号按 probe 级别缩小，而不是只改标签不改仓位

默认值保持为 `1.0`，因此不会影响当前正式候选。

## 2. 回归验证

已通过：

- `pytest tests/test_v71_live.py`
- `py_compile src/btc_regime/v71_live.py`

## 3. 真实数据验证

基线版本：

- `baseline_rebalanced`

测试版本：

- `cool_probe_12_4_s050`
- `cool_probe_12_6_s050`
- `cool_probe_16_4_s050`
- `cool_probe_12_4_s065`
- `cool_probe_12_6_s065`

其中：

- `12 / 4` 表示 `long_fast_fail_bars = 12`、`long_fast_fail_cooldown_bars = 4`
- `s050` 表示 `long_fast_fail_probe_scale = 0.50`

## 4. 结果摘要

| candidate | total_return | sharpe | calmar | max_drawdown | ret_2021 | ret_2023 |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_rebalanced` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` | `-5.41%` | `70.55%` |
| `cool_probe_12_4_s065` | `109.47%` | `0.7120` | `0.6539` | `-18.18%` | `-6.19%` | `68.58%` |
| `cool_probe_12_6_s065` | `109.47%` | `0.7120` | `0.6539` | `-18.18%` | `-6.19%` | `68.58%` |
| `cool_probe_16_4_s050` | `108.90%` | `0.7102` | `0.6573` | `-18.02%` | `-6.35%` | `68.33%` |
| `cool_probe_12_4_s050` | `108.70%` | `0.7094` | `0.6536` | `-18.09%` | `-6.35%` | `68.33%` |
| `cool_probe_12_6_s050` | `108.70%` | `0.7094` | `0.6536` | `-18.09%` | `-6.35%` | `68.33%` |

## 5. 2021 long 细节

基线：

- `long_2021_pnl = -1042.86`

probe cooldown 版本：

- 最好的也只有 `-1145.05`
- 更差的到 `-1165.90`

这说明当前实现下，probe cooldown 并没有修好 `2021 long`，反而更差。

## 6. 为什么这条线没通过

这轮结果说明，当前语义下的 probe cooldown 仍然有两个问题：

1. 它确实会降低 long 暴露，但降低的位置不够精准  
   不是只打到 `2021` 的坏 long，也会打到正常 long continuation。

2. 它伤害强趋势年的副作用仍然明显  
   `2023` 和全样本 `Sharpe / Calmar` 都同步变差。

换句话说：

**这版 probe cooldown 已经比“直接封死再入场”更合理，但仍然不够精准。**

## 7. 当前结论

本轮没有产生新的正式候选。

当前主候选继续保持为：

- [v71_final_candidate_risk_adjusted_rebalanced_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_params.json)
- [v71_final_candidate_risk_adjusted_rebalanced_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_execution.json)

## 8. 后续更值得研究的方向

如果后面继续做这条机制线，更值得尝试的不是继续拧 `bars / cooldown / scale`，而是改触发语义，例如：

1. 只对 `probe_long` 失败后的再入场生效  
   不碰已经证明自己是 continuation 的 long。

2. 只对 `trend_trailing_stop` 且同时满足低趋势质量的退出生效  
   避免把正常回撤中的强趋势也打成冷却对象。

3. 冷却期不直接缩仓，而是提高 `long_continuation_threshold`  
   让再入场更难升级为 full continuation，而不是一刀切缩小所有 long。

当前阶段最稳妥的结论是：

**保留这版代码作为研究钩子，但不把 probe cooldown 纳入正式候选。**

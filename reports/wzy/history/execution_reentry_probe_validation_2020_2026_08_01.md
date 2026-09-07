# Execution Reentry Probe Validation

这轮继续优化的目标，是把此前“打不中 2021 微观亏损路径”的问题往执行层下沉。

核心判断是：

- `2021` 里很多坏 long 并不是信号层提前结束趋势
- 而是在 `micro_backtest` 里被 `stop_loss / signal` 很快打掉

因此，本轮不再继续拧 signal 层 cooldown，而是新增一个执行层研究钩子：

**当 low-quality `confirmed_long` 在较短持有时间内以亏损 `stop_loss / signal` 结束后，后续一段时间内的 long 再入场只允许 probe 级别仓位。**

## 1. 代码改动

新增执行层配置项：

- `long_loss_reentry_probe_enabled`
- `long_loss_reentry_probe_cooldown_minutes`
- `long_loss_reentry_probe_max_holding_minutes`
- `long_loss_reentry_probe_quality_max`
- `long_loss_reentry_probe_scale`

位置：

- [micro_backtest.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/src/btc_regime/micro_backtest.py)

这些参数默认关闭，因此不会影响当前正式候选。

## 2. 回归验证

已通过：

- [test_strategy.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/tests/test_strategy.py)
- [test_v71_live.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/tests/test_v71_live.py)

并通过：

- `py_compile src/btc_regime/micro_backtest.py`
- `py_compile src/btc_regime/v71_live.py`

## 3. 实盘化验证设置

基线：

- `rebalanced`

代表性执行层变体：

1. `exec_probe_24h_q075_s065`
   - `cooldown = 24h`
   - `quality_max = 0.75`
   - `probe_scale = 0.65`

2. `exec_probe_24h_q080_s080`
   - `cooldown = 24h`
   - `quality_max = 0.80`
   - `probe_scale = 0.80`

## 4. live-like 结果

| candidate | total_return | sharpe | calmar | max_drawdown | ret_2021 | ret_2023 |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_rebalanced` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` | `-5.41%` | `70.55%` |
| `exec_probe_24h_q075_s065` | `103.80%` | `0.7118` | `0.6458` | `-17.69%` | `-5.99%` | `68.16%` |
| `exec_probe_24h_q080_s080` | `80.42%` | `0.6239` | `0.5301` | `-17.69%` | `-4.90%` | `48.86%` |

## 5. 2021 与 2023 的 trade-off

这一轮最关键的发现是：

- 更宽松的执行层 probe（`q080_s080`）确实能稍微改善 `2021 long`
  - `long_2021_pnl: -1042.86 -> -871.94`
- 但它会严重压掉 `2023`
  - `long_2023_pnl: 8914.72 -> 5890.14`

更克制的版本（`q075_s065`）副作用较小，但：

- 既没修好 `2021`
- 也没有保住全样本风报

## 6. 结论

这轮执行层机制比 signal 层 probe cooldown 更接近真实问题位置，但结果仍然不够好：

- 它终于能命中 `2021` 的坏 long 路径
- 但一旦真的开始起作用，就会明显压掉 `2023`
- 全样本 `Sharpe / Calmar` 也同步下降

因此，本轮仍然没有产生新的正式候选。

当前主候选继续保持：

- [v71_final_candidate_risk_adjusted_rebalanced_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_params.json)
- [v71_final_candidate_risk_adjusted_rebalanced_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_execution.json)

## 7. 更值得继续研究的方向

如果继续走执行层这条线，更值得做的不是继续拧：

- `cooldown_minutes`
- `quality_max`
- `probe_scale`

而是进一步提高触发精准度，例如：

1. 只对 `stop_loss` 生效，不对普通 `signal` 退出生效
2. 只对“短持有 + 低质量 + confirmed_long”同时满足的情况生效
3. 只限制再入场的前一两次加仓，而不是整个 cooldown 窗口都压 probe

当前阶段更稳妥的结论是：

**执行层 reentry probe 作为研究钩子保留，但不进入正式候选。**

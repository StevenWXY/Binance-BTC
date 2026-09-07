# Execution Reentry Probe Stop-Loss-Only Validation

本轮继续沿着执行层 `reentry probe` 方向优化，但把触发条件进一步收窄为：

- 只对 `stop_loss` 生效
- 只对短持有的 low-quality `confirmed_long` 生效
- 只限制前 `1` 次 long 再入场

目标是：

- 更精准地命中 `2021` 的坏 long 循环
- 尽量避免持续压制 `2023` 的强趋势 continuation

## 1. 代码层调整

在 [micro_backtest.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/src/btc_regime/micro_backtest.py) 中新增了两项默认关闭配置：

- `long_loss_reentry_probe_stop_loss_only`
- `long_loss_reentry_probe_max_reentries`

配合上一轮已有参数后，执行层 `reentry probe` 现在支持：

- 只对 `stop_loss` 型早失败生效
- 只限制 cooldown 窗口内前若干次 long 再入场

对应测试已补充在：

- [test_strategy.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/tests/test_strategy.py)

## 2. 验证结果

### 第一组：有实际作用的代表性版本

| candidate | total_return | sharpe | calmar | max_drawdown | ret_2021 | ret_2023 |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_rebalanced` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` | `-5.41%` | `70.55%` |
| `stoploss_once_24h_q075_s065` | `105.20%` | `0.6956` | `0.6751` | `-17.09%` | `-5.79%` | `68.15%` |
| `stoploss_once_12h_q080_s080` | `105.65%` | `0.6947` | `0.6769` | `-17.10%` | `-5.75%` | `61.24%` |

结论：

- 一旦这条机制真正开始生效，`2023` 仍会被明显压掉
- 同时 `2021` 也没有改善，反而略差
- 全样本 `Sharpe / Calmar` 同步下降

### 第二组：更轻手的版本

| candidate | total_return | sharpe | calmar | max_drawdown | ret_2021 | ret_2023 |
|---|---:|---:|---:|---:|---:|---:|
| `baseline_rebalanced` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` | `-5.41%` | `70.55%` |
| `stoploss_once_12h_q070_s090` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` | `-5.41%` | `70.55%` |
| `stoploss_once_8h_q070_s095` | `128.17%` | `0.7721` | `0.7807` | `-17.10%` | `-5.41%` | `70.55%` |

结论：

- 更轻的版本已经收窄到几乎完全不触发
- 它们与基线结果完全一致

## 3. 这轮的核心判断

这轮把执行层 `reentry probe` 收得更精准以后，结果呈现出很清楚的二分：

- **触发得动**：会伤 `2023`，而且修不好 `2021`
- **不伤 `2023`**：又基本不触发，等于没有作用

这说明当前这类“亏损后再入场降级”的机制，虽然已经比 signal 层版本更接近真实问题，但依然没有抓到真正值得拦截的坏循环。

## 4. 当前结论

本轮没有产生新的正式候选。

当前主候选继续保持：

- [v71_final_candidate_risk_adjusted_rebalanced_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_params.json)
- [v71_final_candidate_risk_adjusted_rebalanced_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_execution.json)

## 5. 后续更值得尝试的方向

如果继续从机制上修 `2021 long`，更值得尝试的不是继续拧 `reentry probe` 参数，而是换一个更贴近问题本体的切入点，例如：

1. 只对 `low-quality confirmed_long` 的初始仓位更轻，不碰后续 continuation  
2. 对 `confirmed_long` 引入更强的“早期 stop 宽度分层”，而不是亏损后再去限制再入场  
3. 把 `confirmed_long` 拆成更明确的 `initial / add-on` 两段，单独收紧初始腿

当前阶段最稳妥的结论是：

**执行层 `reentry probe` 研究线暂时可以收口，主候选仍保持 `rebalanced`。**

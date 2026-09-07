# 三路线同口径回测与最终候选结论

## 1. 结论先行

本轮工作在 `Binance-BTC-wzy/` 内完成了三件事：

1. 将 `main_v43`、`xuyujian_v71_ref`、`wzy_v71_live` 放到同一执行口径下做全样本回测。
2. 基于 `wzy_v71_live` 做小范围参数扫描，并筛出两个候选版本：
   - `balanced_recovery`
   - `ref_plus_live`
3. 对这两个候选分别做了**全样本同口径回测 + stress**。

截至当前轮次，最终结论是：

- 如果目标是“尽量保持回撤优势”，`balanced_recovery` 在持出期扫描里更符合方向。
- 但回到**全样本同口径**后，`balanced_recovery` 明显退化，不适合作为最终候选。
- `ref_plus_live` 虽然没有超越 `main_v43` 或 `xuyujian_v71_ref`，但在两套候选里表现更完整、更稳定。
- 因此，当前建议把 **`ref_plus_live` 作为 `wzy` 路线的研究终选版本**。
- 但在更贴近实盘的验证里，它暴露出一个关键问题：**2021-2026 基本没有继续交易**。因此，它还不能直接视为“可上实盘的最终版本”。

当前研究终选配置文件：

- 参数：[configs/v71_final_candidate_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_params.json)
- 执行：[configs/v71_final_candidate_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_execution.json)

## 2. 回测口径

### 2.1 数据口径

- 交易标的：`BTCUSDT`
- 信号层：4h K 线
- 执行层：1m 成交与标记价格
- 资金费：Binance USD-M funding archive
- 全样本窗口：`2020-01-01 ~ 2026-08-01`
- 持出期扫描窗口：`2023-01-01 ~ 2026-08-01`
- 如果评价窗口晚于 2020，仍从 `2020-01-01` 加载 warm-up

### 2.2 执行口径

统一执行配置基线：
[configs/v71_live_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_live_execution.json)

核心假设：

| 项目 | 数值 |
| --- | ---: |
| taker fee | `4.0 bps` |
| maker fee | `0.2 bps` |
| maker offset | `0.5 bps` |
| maker timeout | `60 min` |
| base slippage | `1.0 bps` |
| impact | `8.0 bps` |
| max minute participation | `2%` |
| liquidation fee | `50.0 bps` |

账户级 governor 基线：

| 档位 | 阈值 | 缩放 |
| --- | ---: | ---: |
| level 1 | `8%` | `0.80x` |
| level 2 | `12%` | `0.50x` |
| level 3 | `16%` | `0.00x` |

### 2.3 因果口径

- 只使用已完成的 4h bar 生成信号
- 仓位在下一执行边界生效
- 保护退出与强平在 1m 路径中触发
- maker 只有在 1m 价格真正触达时才成交

## 3. 三条基线策略

### 3.1 `main_v43`

来源：
[configs/v4_3_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v4_3_params.json)

定位：

- V4.1 方向框架
- maker 执行
- 快速下跌保护
- ATR 显式止损/止盈

### 3.2 `xuyujian_v71_ref`

来源：
[configs/v71_reference_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_reference_params.json)

定位：

- `range / trend_up / trend_down` 三态
- 日线偏置 + 4h 触发
- 对称趋势做空
- 不启用 live protection

### 3.3 `wzy_v71_live`

来源：
[configs/v71_live_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_live_params.json)

定位：

- 以 `V7.1` 为骨架
- 更保守的做空预算
- 更严格的趋势确认
- 启用 live protection 与账户级 governor

## 4. 三条基线的全样本同口径结果

结果目录：
[reports/three_branch_same_basis_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/three_branch_same_basis_2020_2026_08_01)

| 策略 | Final Equity | CAGR | Sharpe | Sortino | Calmar | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `main_v43` | `16621.82` | `0.0803` | `0.6463` | `1.1622` | `0.5211` | `-15.40%` |
| `xuyujian_v71_ref` | `14224.49` | `0.0550` | `0.5655` | `1.0569` | `0.4031` | `-13.64%` |
| `wzy_v71_live` | `13054.96` | `0.0413` | `0.4518` | `0.6858` | `0.3440` | `-12.01%` |

解读：

- `main_v43` 是当前三者中综合最强的基线。
- `xuyujian_v71_ref` 的收益效率好于当前 `wzy_v71_live`。
- `wzy_v71_live` 的优点是回撤最小，但收益效率不足。

## 5. 小范围参数扫描

扫描脚本：
[scripts/scan_v71_live_small_range.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/scripts/scan_v71_live_small_range.py)

扫描目标：

- 尽量保持 `max_drawdown` 优势
- 把 `Sharpe / Calmar` 往 `xuyujian_ref`，甚至 `main_v43` 靠

扫描结果目录：
[reports/v71_live_small_scan_2023_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/v71_live_small_scan_2023_2026_08_01)

扫描后保留两个候选：

### 5.1 `balanced_recovery`

文件：

- 参数：[configs/v71_balanced_recovery_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_balanced_recovery_params.json)
- 执行：[configs/v71_balanced_recovery_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_balanced_recovery_execution.json)

核心变化：

- `breakout_buffer_atr: 0.25 -> 0.20`
- `trend_confirm_bars: 3 -> 2`
- `short_scale: 0.10 -> 0.08`
- `rapid_deceleration_scale: 0.40 -> 0.35`
- governor 更早介入：
  - `7% -> 0.75x`
  - `11% -> 0.45x`
  - `15% -> 0.00x`

### 5.2 `ref_plus_live`

文件：

- 参数：[configs/v71_ref_plus_live_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_ref_plus_live_params.json)
- 执行：[configs/v71_ref_plus_live_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_ref_plus_live_execution.json)

核心变化：

- 用 `xuyujian_ref` 的骨架替换更保守的 `wzy_v71_live` 骨架
- 同时保留 live protection
- 同时保留账户级 governor
- 主要特征：
  - `max_leverage = 6.0`
  - `trend_scale = 1.6`
  - `short_scale = 0.12`
  - `breakout_buffer_atr = 0.20`
  - `trend_confirm_bars = 2`
  - `trend_exit_confirm_bars = 4`

## 6. 候选版本全样本验证

### 6.1 `balanced_recovery`

结果目录：
[reports/balanced_recovery_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/balanced_recovery_validation_2020_2026_08_01)

同口径结果：

| 策略 | Final Equity | Sharpe | Calmar | Max DD |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `15551.98` | `0.6030` | `0.4764` | `-14.57%` |
| `xuyujian_v71_ref` | `14440.23` | `0.6215` | `0.4800` | `-11.96%` |
| `balanced_recovery` | `10891.07` | `0.1852` | `0.0930` | `-14.03%` |

Stress 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -12.71%`
- `mean_drawdown_improvement = 0.0876`

评价：

- 抗压性不错
- 但全样本收益效率明显不足
- 不适合作为最终候选版本

### 6.2 `ref_plus_live`

结果目录：
[reports/ref_plus_live_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_validation_2020_2026_08_01)

同口径结果：

| 策略 | Final Equity | Sharpe | Calmar | Max DD |
| --- | ---: | ---: | ---: | ---: |
| `main_v43` | `16621.82` | `0.6463` | `0.5211` | `-15.40%` |
| `xuyujian_v71_ref` | `14224.49` | `0.5655` | `0.4031` | `-13.64%` |
| `ref_plus_live` | `12564.56` | `0.3577` | `0.2787` | `-12.66%` |

Stress 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -16.23%`
- `mean_drawdown_improvement = 0.0619`

评价：

- 全样本表现明显好于 `balanced_recovery`
- 仍保住了比 `main_v43` 和 `xuyujian_v71_ref` 更小的全样本回撤
- 虽然 `Sharpe / Calmar` 还没有追上两条参考线，但已是当前两套候选里更稳的选择

## 7. 第二轮局部微调

第二轮局部微调脚本：
[scripts/scan_ref_plus_live_round2.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/scripts/scan_ref_plus_live_round2.py)

结果目录：
[reports/ref_plus_live_round2_scan_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_round2_scan_2020_2026_08_01)

这轮只围绕 6 个关键参数做本地微调：

- `short_scale`
- `trend_scale`
- `breakout_buffer_atr`
- `trend_confirm_bars`
- `trend_exit_confirm_bars`
- `trailing_stop_atr`

Top 结果如下：

| 候选 | Sharpe | Calmar | Max DD | 结论 |
| --- | ---: | ---: | ---: | --- |
| `breakout_022_exit3` | `0.3697` | `0.2980` | `-12.09%` | 第二轮最佳，小幅优于 baseline |
| `lighter_short_010` | `0.3645` | `0.2896` | `-12.46%` | 也有改善，但不如第一名 |
| `baseline` | `0.3577` | `0.2787` | `-12.66%` | 现有 ref_plus_live |

最优局部候选文件：

- 参数：[configs/v71_ref_plus_live_round2_best_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_ref_plus_live_round2_best_params.json)
- 执行：[configs/v71_ref_plus_live_round2_best_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_ref_plus_live_round2_best_execution.json)

需要注意的是：

- 这轮第二局部微调只带来**很小幅度**改善
- 它没有改变更大的结构性问题：近几年交易活跃度过低

## 8. 更贴近实盘的验证

验证脚本：
[scripts/run_ref_plus_live_live_like_validation.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/scripts/run_ref_plus_live_live_like_validation.py)

结果目录：
[reports/ref_plus_live_live_like_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_live_like_validation_2020_2026_08_01)

这份验证不只看总收益，还额外拆了：

- 年度表现
- 最近窗口表现
- 年度活跃度
- maker / taker 分解
- 资金费支出
- 多空分解
- 退出原因分解

最关键的结果是：

### 8.1 年度活跃度

[activity_by_year.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_live_like_validation_2020_2026_08_01/activity_by_year.csv)

| 年份 | fill_count | trade_count |
| --- | ---: | ---: |
| `2020` | `217` | `74` |

这意味着：

- 现有 `ref_plus_live` 的成交和交易几乎全部发生在 `2020`
- `2021-2026` 基本没有继续交易

### 8.2 最近窗口

[recent_metrics.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_live_like_validation_2020_2026_08_01/recent_metrics.csv)

| 窗口 | Total Return | Sharpe | Max DD |
| --- | ---: | ---: | ---: |
| `2024-2026-08` | `0.0` | `0.0` | `0.0` |
| `2025-2026-08` | `0.0` | `0.0` | `0.0` |
| `2026 YTD` | `0.0` | `0.0` | `0.0` |

这不是“最近表现平平”，而是“最近几乎没出手”。

### 8.3 执行与成本

[fill_liquidity_breakdown.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_live_like_validation_2020_2026_08_01/fill_liquidity_breakdown.csv)

- `maker_fill_ratio = 0.7497`
- `maker_fee_saved_vs_taker = 467.38`
- `fees_paid = 518.13`
- `funding_paid = 443.22`

说明：

- maker 追求是有效的
- 但当前问题不在执行细节，而在信号活跃度过低

### 8.4 多空与退出原因

[trade_side_breakdown.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_live_like_validation_2020_2026_08_01/trade_side_breakdown.csv)  
[trade_exit_reason_breakdown.csv](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/ref_plus_live_live_like_validation_2020_2026_08_01/trade_exit_reason_breakdown.csv)

- 多头：`54` 笔，`win_rate = 48.15%`，总 PnL `+2744.31`
- 空头：`20` 笔，`win_rate = 25.00%`，总 PnL `-179.75`
- `stop_loss`: `41` 笔，总 PnL `-6226.20`
- `take_profit`: `21` 笔，总 PnL `+8834.96`

说明：

- 当前利润主要还是来自多头 + take profit
- 空头并没有形成明显优势

## 9. 当前研究终选

当前建议把 **`ref_plus_live` 定为研究终选版本**，不是实盘终选版本。

正式候选文件：

- 参数：[configs/v71_final_candidate_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_params.json)
- 执行：[configs/v71_final_candidate_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_execution.json)

选择它的原因不是“它已经最优”，而是：

1. 在两套候选里，它的全样本表现更完整。
2. 它保留了 live protection + governor 的实盘友好结构。
3. 它的全样本最大回撤仍优于 `main_v43` 和 `xuyujian_v71_ref`。
4. 它在 stress 下全部生存、无强平，说明保护层是有效的。

不选择 `balanced_recovery` 的原因也很明确：

- 它在持出期扫描里更好
- 但回到全样本后收益效率明显塌下去
- 这说明它更像“扫描窗口赢家”，还不是“最终候选赢家”

但更贴近实盘的验证也表明：

- 它的近几年活跃度严重不足
- 因此当前还不能直接推到实盘测试

## 10. 当前判断

截至现在，更准确的项目判断是：

- `main_v43` 仍然是当前最强的工程化基线
- `xuyujian_v71_ref` 仍然代表更完整的 V7.1 原始进攻框架
- `wzy` 这条线已经确认：
  - live protection 有价值
  - governor 有价值
  - 但参数还没把收益效率调到足够接近参考线

所以这轮工作的真正结果不是“wzy 已经赢了”，而是：

> `wzy` 已经从“方向正确但过于保守”推进到了“有一个经过两轮筛选的研究终选版本”，并且它已经通过了全样本同口径、stress 和一次更贴近实盘的验证；但这个版本还暴露出近几年几乎不交易的关键问题。

## 11. 下一步建议

下一步最值得做的，不是再大范围扫参数，而是围绕研究终选版做两件更聚焦的事情：

1. 优先解决“2021-2026 基本不交易”的问题  
   重点排查：
   - 日线偏置是不是过严
   - 三态切换阈值是不是把系统卡死在 `range`
   - breakout buffer / confirm bars 是否导致长期不触发
   - governor 与 live protection 是否过早把风险降到零

2. 只在确认活跃度恢复后，再继续优化收益效率  
   优先看：
   - `daily_confirm_days`
   - `daily_exit_confirm_days`
   - `breakout_buffer_atr`
   - `trend_confirm_bars`
   - `trend_exit_confirm_bars`
   - `short_scale`

如果目标是“离实盘更近”，那么接下来最该优先解决的已经不是 maker 细节，而是：

- 为什么近几年不交易
- 交易恢复后收益来自哪里
- 交易恢复后回撤来自哪里

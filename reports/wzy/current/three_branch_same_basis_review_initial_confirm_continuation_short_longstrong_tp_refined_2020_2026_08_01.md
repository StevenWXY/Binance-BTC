# Three-Branch Same-Basis Review: wzy_v72 TP Refined

这份文档用于给合作者快速理解当前 `wzy` 主候选的对外版本、回放口径、机制位置和关键参数。

先说明版本映射，避免和 `xuyujian_v71_ref` 混淆：

- 当前 `wzy` 主候选的**对外版本编号**统一记为 `wzy_v72`
- 当前验证目录中的 candidate code 仍是 `initial_confirm_continuation_short_longstrong_tp_refined`
- 底层实现文件仍然是 [v71_live.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/src/btc_regime/v71_live.py)，这表示它沿用 `v71_live` 这条 engine lineage，而**不表示当前主候选仍应对外称为 `v71`**

当前主候选入口：

- 参数：[wzy_v72_tp_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/wzy_v72_tp_refined_params.json)
- 执行：[wzy_v72_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/wzy_v72_execution.json)
- 验证目录：[initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/wzy/validations/initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01)

## 1. 这份复核在回答什么

这轮 same-basis 复核关注的是：

1. very-strong long 的 `take-profit widening` 是否真的带来净增益；
2. `wzy_v72` 是否在统一口径下正式超过 `main_v43`；
3. 这种提升是否是在维持低回撤结构的前提下取得的。

## 2. 回放口径

这份文档里的三分支结果，使用的是 **same-basis minute execution replay**。

具体口径是：

- 数据范围：`2020-01-01` 到 `2026-08-01`
- 信号层：
  - `main` 使用 `generate_v43_signals(...)`
  - `xuyujian` 使用 `generate_v71_live_signals(...)`
  - `wzy_v72` 也使用 `generate_v71_live_signals(...)`
- 执行层：三条分支都统一送入同一套 `run_micro_backtest(...)`
- 执行参数：三条分支共用 [wzy_v72_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/wzy_v72_execution.json)

这套统一执行口径包含：

- taker fee `4 bps`
- base slippage `1 bp`
- impact `8 bps`
- maker enabled，maker fee `0.2 bps`
- maker timeout `60 min`
- strategy-level Governor：
  - level 1: `8% -> 0.8x`
  - level 2: `12% -> 0.5x`
  - level 3: `16% -> flat`
- recovery reentry enabled

### 与 main 自己分支里回放的区别

这里的 `main_v43` 结果，**不是**直接照抄 `main` 分支各自文档里的原生回放结果，而是：

- 先用 `main_v43` 的信号引擎生成信号
- 再把这些信号放到本地统一的 minute execution / maker / Governor 口径里重放

因此，这里的 `main_v43` 更像是：

**“把 `main` 的信号 alpha 放进和 `wzy_v72` 一样的执行环境里，做 apples-to-apples 比较”**

这和 `main` 自己分支里的原生回放相比，可能出现差异，原因通常是：

- execution config 不同
- maker / taker 假设不同
- Governor 细节不同
- protection / rebalance 的 minute-level 落地环境不同

所以这份文档适合回答：

- 在统一执行环境下，三条分支谁的综合结构更优

但它**不等同于**：

- 复述 `main` 分支原始文档里的 native replay 结论

## 3. 全样本三分支结果

| strategy | total_return | sharpe | calmar | max_drawdown |
| --- | ---: | ---: | ---: | ---: |
| `wzy_v72` | `472.09%` | `1.3375` | `1.7671` | `-17.17%` |
| `main_v43` | `352.81%` | `1.1053` | `1.3481` | `-19.13%` |
| `xuyujian_v71_ref` | `88.00%` | `0.6294` | `0.4365` | `-23.06%` |

解读：

- `wzy_v72` 继续显著高于 `xuyujian_v71_ref`
- `wzy_v72` 已经在 same-basis 口径下超过 `main_v43`
- 而且不是只在单个指标上略胜

### 分年度拆分（same-basis，自然年）

为了便于合作者判断表现是否集中在少数年份，这里把同一套 same-basis equity curve 按自然年拆开重算。

说明：

- `2020-2025` 为完整自然年
- `2026` 为 `2026-01-01` 到 `2026-08-01` 的 YTD 结果
- 下面的年度指标与全样本主表使用同一套 execution replay，只是把统计区间改成按年切片

#### 年度 `total_return` 与 `sharpe`

| year | `wzy_v72` return | `main_v43` return | `xuyujian_v71_ref` return | `wzy_v72` sharpe | `main_v43` sharpe | `xuyujian_v71_ref` sharpe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `2020` | `41.97%` | `165.98%` | `40.12%` | `1.5582` | `2.6668` | `1.3830` |
| `2021` | `-2.20%` | `36.62%` | `-0.60%` | `-0.1374` | `1.2934` | `-0.0315` |
| `2022` | `0.29%` | `-4.94%` | `0.36%` | `0.0797` | `-0.2811` | `0.1081` |
| `2023` | `143.48%` | `23.86%` | `38.54%` | `2.6907` | `0.9263` | `1.1321` |
| `2024` | `17.53%` | `5.98%` | `-3.55%` | `0.8685` | `0.4314` | `-0.3194` |
| `2025` | `29.63%` | `0.74%` | `0.79%` | `1.5346` | `0.1811` | `0.2314` |
| `2026 YTD` | `10.71%` | `-0.92%` | `-0.18%` | `1.0270` | `-0.6340` | `-0.1400` |

#### 年度 `calmar` 与 `max_drawdown`

| year | `wzy_v72` calmar | `main_v43` calmar | `xuyujian_v71_ref` calmar | `wzy_v72` max DD | `main_v43` max DD | `xuyujian_v71_ref` max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `2020` | `3.3252` | `10.7552` | `2.2376` | `-12.60%` | `-15.39%` | `-17.90%` |
| `2021` | `-0.1780` | `2.4153` | `-0.0766` | `-12.37%` | `-15.18%` | `-7.80%` |
| `2022` | `0.0394` | `-0.3099` | `0.1086` | `-7.36%` | `-15.94%` | `-3.33%` |
| `2023` | `15.4778` | `1.2488` | `1.6737` | `-9.29%` | `-19.13%` | `-23.06%` |
| `2024` | `1.0194` | `0.4324` | `-0.3906` | `-17.17%` | `-13.80%` | `-9.07%` |
| `2025` | `3.0899` | `0.1663` | `0.3053` | `-9.60%` | `-4.48%` | `-2.59%` |
| `2026 YTD` | `3.1618` | `-0.9370` | `-0.2192` | `-6.06%` | `-1.69%` | `-1.41%` |

年度视角下，几个信号比较清楚：

- `main_v43` 在 `2020-2021` 的趋势年仍然最强，这说明它的成熟趋势基线属性没有消失
- `wzy_v72` 的优势主要来自 `2023-2026 YTD` 的连续占优，而不是只押中单一年份
- `xuyujian_v71_ref` 没有明显“爆发年”，更像 reference baseline，而不是当前可竞争主候选

## 4. 分层结果

### 训练段 `2020-2022`

- `Sharpe = 0.7489`
- `Calmar = 0.9097`

### 验证段 `2023-2024`

- `Sharpe = 1.9460`
- `Calmar = 4.0246`

### 留出段 `2025-2026_07`

- `Sharpe = 1.3424`
- `Calmar = 2.6760`

分层表现说明：

- 训练段没有被明显打坏
- 验证段显著增强
- 留出段同步显著增强

这说明新增的 TP widening 不是只靠样本内收益堆出来的。

## 5. 三个分支在机制上的异同

### 共同点

三条分支的共性并不多，但有两个关键点是相同的：

- 都是在 `BTCUSDT` 上做趋势/状态判断后输出方向性仓位
- 都能在 minute execution 层接入 maker、fee、slippage 和 Governor 回放

### `main_v43`

`main_v43` 更像一套较成熟的趋势执行框架，特点是：

- 方向引擎更简单直接
- 保护和执行语义更统一
- 在 same-basis 下依然保持很强的趋势赚钱效率

它的优势主要是：

- 强趋势段吃得深
- `Sharpe / Calmar` 长期稳定

### `xuyujian_v71_ref`

`xuyujian_v71_ref` 是 `v71_live` 结构的参考版本，特点是：

- 已经有 `v71_live` 的方向/可交易性框架
- 但多空阀门、early-leg 管理、Governor 恢复语义没有被 `wzy` 那样继续细化

它的作用更像：

- 作为 `v71` 结构的 reference baseline

### `wzy_v72`

`wzy_v72` 继承了 `v71_live` 的主干，但已经不是 reference 级别的小修，而是一条**独立演化出来的策略线**。

当前 `wzy_v72` 的关键机制可以概括成 5 条：

1. `initial confirm`  
   对 low-quality `confirmed_long` 的初始腿降杠杆，减少短命 early long。

2. `initial confirm release rebalance`  
   初始腿缩放结束时强制释放，避免因为 `min_rebalance_delta` 挂住低仓位。

3. `continuation add-on`  
   只对高质量、证据连续满足的 long continuation 做小幅加仓，提升顶级趋势段参与效率。

4. `short initial confirm`  
   只收紧 `confirmed_short` 的前几根 bar，减少早期低质量 short 的止损消耗。

5. `strong long protection + strong long take-profit widening`  
   对 very-strong `confirmed_long` 同时放宽 stop breathing room 和 take-profit 距离，减少“对的趋势拿不住”的问题。

所以如果一句话概括三者关系：

- `main_v43`：强趋势赚钱效率高的成熟基线
- `xuyujian_v71_ref`：`v71_live` 参考版
- `wzy_v72`：在 `v71_live` 结构上，围绕 long 初始腿、continuation、short 初始腿、strong-long protection 连续迭代出来的独立版本

## 6. `wzy_v72` 的主要参数

完整参数见 [wzy_v72_tp_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/wzy_v72_tp_refined_params.json)。  
为了方便合作者阅读，这里只摘当前最重要的一组。

### 风险预算与基础仓位

- `target_vol = 0.78`
- `max_leverage = 6.0`
- `trend_scale = 1.30`
- `rebound_scale = 0.11`
- `short_scale = 0.08`
- `min_rebalance_delta = 0.35`

### Long 侧参与与初始腿

- `long_permission_scale = 1.08`
- `long_weak_permission_multiplier = 0.94`
- `long_min_permission = 0.13`
- `long_continuation_threshold = 0.59`
- `long_initial_confirm_bars = 3`
- `long_initial_confirm_scale = 0.78`
- `long_initial_confirm_quality_max = 0.70`

### Long continuation add-on

- `long_continuation_add_on_min_bars = 8`
- `long_continuation_add_on_confirm_bars = 2`
- `long_continuation_add_on_scale = 1.04`
- `long_continuation_add_on_quality_min = 0.84`
- `long_continuation_add_on_tradability_min = 0.84`

### Short 初始腿控制

- `short_initial_confirm_bars = 2`
- `short_initial_confirm_scale = 0.94`
- `short_permission_scale = 0.92`
- `short_weak_permission_multiplier = 0.72`
- `short_min_permission = 0.11`

### Strong long protection / TP widening

- `long_strong_protection_atr_bonus = 0.9`
- `long_strong_protection_quality_min = 0.88`
- `long_strong_protection_tradability_min = 0.88`
- `long_strong_take_profit_atr_bonus = 1.5`
- `long_strong_take_profit_quality_min = 0.88`
- `long_strong_take_profit_tradability_min = 0.88`

### Live protection

- `stop_atr = 1.8`
- `take_profit_atr = 3.2`
- `trailing_stop_atr = 1.65`
- `max_hold_bars = 96`
- `exit_cooldown_bars = 3`

## 7. stress 结果

stress suite 聚合结果：

- `scenario_survival_rate = 1.0`
- `liquidation_run_count = 0`
- `worst_max_drawdown = -10.27%`
- `worst_total_return = -5.63%`
- `protection_improved_scenario_count = 8`
- `protection_improved_run_count = 13`
- `mean_drawdown_improvement = 0.0324`

没有出现新的失稳或清算问题。

## 8. 三分支的过拟合风险比较

如果从“当前结果是否可能只是样本内调出来的”这个角度看，三条分支的相对风险大致如下。

| strategy | 过拟合风险判断 | 主要依据 | 需要保留的担忧 |
| --- | --- | --- | --- |
| `main_v43` | `中等` | 结构成熟、参数语义相对统一，不像近期专门为某一小段样本做过密集调优 | 在这套 same-basis 回放里，`2025-2026 YTD` 已明显走弱，说明它对当前执行环境和近年 regime 的适配不如历史样本强 |
| `xuyujian_v71_ref` | `偏低` | 更像 reference baseline，近期没有被沿着新机制反复打磨，因而“被研究流程过度雕刻”的风险较低 | 风险低不等于值得用；它更像“没有明显过拟合，但整体 alpha 也偏弱” |
| `wzy_v72` | `中等偏可控` | 虽然经历了连续机制迭代，但验证段 `2023-2024` 和留出段 `2025-2026 YTD` 都明显强，且按自然年看是 `6/7` 个年份为正、`2023-2026 YTD` 连续占优 | 它的复杂度和研究参与度高于另外两条线，因此仍需警惕“机制叠加过多后只对当前样本有效”的风险，后续最好继续做更严格的留出与扰动验证 |

如果再把三者放在一起看，比较稳妥的结论是：

- `main_v43` 不是典型“被近期研究过拟合”的版本，但它在当前 same-basis 环境里的**近年泛化**已经弱于 `wzy_v72`
- `xuyujian_v71_ref` 的问题不是过拟合，而是**信号强度和机制完成度都不够**
- `wzy_v72` 不是“零过拟合风险”，但现有证据更接近**研究驱动的有效机制升级**，而不是只在验证样本里好看的局部优化

因此，就“当前主候选是否具有可向合作者解释的稳健性”而言，`wzy_v72` 的风险画像是：

- **存在研究复杂度带来的中等风险**
- **但已有验证段、留出段、分年度和 stress 结果共同约束，暂不支持把它判断为明显过拟合**

## 9. 当前结论

当前最简洁的结论是：

- `wzy_v72` 是 `v71_live` 结构上的独立演化版，而不是 `xuyujian_v71_ref` 的同名并列版本
- 在统一 same-basis 回放口径下，`wzy_v72` 已经超过 `main_v43`
- 这种超越不是只靠收益堆出来，而是同时体现在 `Sharpe / Calmar / Max DD`

因此，当前 `wzy` 的正式主候选应表述为：

**`wzy_v72`（candidate code: `initial_confirm_continuation_short_longstrong_tp_refined`）**

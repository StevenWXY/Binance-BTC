# Risk-Adjusted Refined Review

本轮继续优化的目标是：

- 在 `risk-adjusted plus` 基础上继续抬高 `Sharpe / Calmar`
- 如果简单调参开始接近瓶颈，则试探低侵入机制创新

## 1. 本轮做了什么

本轮实际上走了两条线：

1. 机制试探
   - 新增 `long_entry_probe_bars / long_entry_probe_scale`
   - 新增 `long_fast_fail_bars / long_fast_fail_cooldown_bars`
   - 这两组参数都默认关闭，不会影响现有候选

2. 继续局部优化
   - 围绕 `risk-adjusted plus` 做更窄的参数扫描
   - 最终得到新的 refined 候选

## 2. 机制试探结论

### 2.1 Long Entry Probe

思路：

- long 趋势进入后的前几根 bar 只给探测仓位
- 如果趋势继续成立，再恢复到正常趋势仓位

结论：

- 在 `same-basis` 快筛里，这个方向整体是负收益的
- 主要问题是它会把强趋势年份一起压掉，尤其会伤 `2023`

因此：

- 这套机制保留在代码里，作为后续研究钩子
- **但本轮不把它启用进正式候选**

### 2.2 Long Fast-Fail Cooldown

思路：

- 如果 long 趋势很快失败，则给后续同向突破一个短冷却
- 目标是减少假突破反复受伤

结论：

- 在 `same-basis` 快筛里，这条线也没有跑出比当前候选更强的结果
- 有些组合能改善个别弱年份，但全样本 `Sharpe / Calmar` 没有胜出

因此：

- 这套机制也先保留为研究钩子
- **暂时不进入正式候选**

## 3. 当前最优方向

本轮真正跑赢当前候选的，不是新机制，而是更窄的参数细化：

- `breakout_buffer_atr: 0.21 -> 0.22`
- `trailing_stop_atr: 1.60 -> 1.65`

其它核心结构保持不变。

## 4. 新候选

- 参数：[v71_final_candidate_risk_adjusted_refined_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_refined_params.json)
- 执行：[v71_final_candidate_risk_adjusted_refined_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_refined_execution.json)

单独 live-like 年度包：

- [final_candidate_risk_adjusted_refined_live_like_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/final_candidate_risk_adjusted_refined_live_like_2020_2026_08_01)

## 5. 与上一版 `risk-adjusted plus` 的对比

上一版 `plus`：

- `total_return = 118.95%`
- `Sharpe = 0.7205`
- `Calmar = 0.7071`
- `Max DD = -17.88%`

新 `refined`：

- `total_return = 124.70%`
- `Sharpe = 0.7499`
- `Calmar = 0.7344`
- `Max DD = -17.82%`

对应变化：

- `total_return`: `+5.75 pct`
- `Sharpe`: `+0.0294`
- `Calmar`: `+0.0273`
- `Max DD`: `+0.06 pct`（更浅）

## 6. 年度结构观察

新候选相对 `plus` 的结构变化大致是：

- `2023` 略弱
- `2026 YTD` 更好
- 全样本风报更高

这组结果的含义是：

- 新候选不是在每个年份都更强
- 但从全样本风险收益比看，它比 `plus` 更优

## 7. 相对 `main / xuyujian` 的当前位置

本轮没有等三分支 compare 脚本完整跑完，因为脚本耗时过长；为了不占住机器，已中止长跑。

不过当前位置其实已经足够清楚：

- `same-basis` 快筛下，refined 候选的 `Sharpe / Calmar` 都高于上一版 `plus`
- `live-like` 单独验证下，refined 候选也高于上一版 `plus`
- 而上一版 `plus` 已经明确高于 `xuyujian_v71_ref`

因此可以较有把握地判断：

- refined 候选仍然高于 `xuyujian`
- refined 候选比 `main` 更近了一步
- 但 **仍未追平 `main_v43`**

## 8. 本轮代码改动

### 已启用到候选中的改动

- refined 参数收敛

### 已进代码但默认关闭的研究钩子

- `long_entry_probe_bars`
- `long_entry_probe_scale`
- `long_fast_fail_bars`
- `long_fast_fail_cooldown_bars`

这些钩子已经通过：

- [test_v71_live.py](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/tests/test_v71_live.py)

的回归测试验证，不会影响默认行为。

## 9. 当前结论

这轮最重要的结论其实很明确：

- `wzy` 现在还没有真正进入“必须依赖机制大改才能继续前进”的状态
- 至少到目前为止，**更窄、更克制的参数细化仍然还能拿到正增量**
- 新机制方向已经开始摸到边界，但还没跑出胜过现有候选的版本

所以当前最合理的判断是：

**继续保留机制创新钩子，但正式候选先用 refined 参数版。**

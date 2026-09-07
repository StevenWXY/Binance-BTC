# Risk-Adjusted Rebalanced Review

这轮继续优化的重点原本是想修 `2021`，但测下来比较明确：

- 直接继续收紧 long 入场，很容易把 `2023` 一起砍掉
- `2021` 的问题不是靠单点把 entry 再拧紧就能漂亮解决

因此这轮最终采用的不是“再收紧 2021 专项参数”，而是：

**继续下调全局风险预算，让系统回到更稳定的风险收益比区间。**

## 1. 新候选

- 参数：[v71_final_candidate_risk_adjusted_rebalanced_params.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_params.json)
- 执行：[v71_final_candidate_risk_adjusted_rebalanced_execution.json](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/configs/v71_final_candidate_risk_adjusted_rebalanced_execution.json)

标准 live-like 年度包：

- [final_candidate_risk_adjusted_rebalanced_live_like_2020_2026_08_01](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/reports/final_candidate_risk_adjusted_rebalanced_live_like_2020_2026_08_01)

## 2. 本轮最终采用的变化

相对上一版 `refined`：

- `target_vol: 0.82 -> 0.78`
- `trend_scale: 1.30` 保持不变
- `breakout_buffer_atr: 0.22` 保持不变
- `trailing_stop_atr: 1.65` 保持不变

注：

- 本轮新增的两个机制研究钩子仍然保留在代码里，但没有启用进正式候选：
  - `long_entry_probe_*`
  - `long_fast_fail_*`

## 3. 为什么这轮这样改

这轮的一个关键发现是：

- `2021` 确实主要是 long 侧亏损
- 但把 long entry 再收紧，会明显破坏 `2023`

所以比起继续局部收紧，更有效的方向反而是：

- 把全局暴露再压一点
- 让系统保住强趋势参与
- 同时减少中等质量年份里的损耗

## 4. live-like 结果

上一版 `refined`：

- `total_return = 124.70%`
- `Sharpe = 0.7499`
- `Calmar = 0.7344`
- `Max DD = -17.82%`

新 `rebalanced`：

- `total_return = 128.17%`
- `Sharpe = 0.7721`
- `Calmar = 0.7807`
- `Max DD = -17.10%`

对应变化：

- `total_return`: `+3.47 pct`
- `Sharpe`: `+0.0222`
- `Calmar`: `+0.0463`
- `Max DD`: `+0.72 pct`（更浅）

## 5. same-basis 快校验

相对 `refined`：

- `Sharpe: 0.9737 -> 1.0003`
- `Calmar: 0.9647 -> 1.0326`
- `Max DD: -28.43% -> -25.37%`

这说明这次改动不是只在 `live-like` 下碰巧好看，统一基础口径下也同方向变强。

## 6. 年度结构变化

相对 `refined`：

- `2021`: 变好
  - `-6.33% -> -5.41%`
- `2023`: 变好
  - `65.98% -> 70.55%`
- `2024`: 变好
  - `4.24% -> 7.66%`

但也有代价：

- `2025`: 变差
  - `-0.14% -> -2.77%`
- `2026`: 略弱
  - `2.63% -> 2.43%`

所以这版不是“所有年份都更好”，而是：

**强趋势年和主要验证年份更好，全样本风报更优，但部分弱年份有回吐。**

## 7. 2021 的细节

2021 这版仍然亏损，但已经比 `refined` 好一点：

- long `2021 pnl`: `-1250.70 -> -1042.86`

这说明：

- 2021 问题还在
- 但当前这次 rebalanced 并不是完全没修到它

## 8. 当前结论

这轮最重要的结论有两个：

1. `2021` 还不能靠简单收紧 long entry 解决。
2. 当前 `wzy` 仍然可以通过更克制的全局风险预算继续抬高 `Sharpe / Calmar`。

所以现阶段更合理的判断是：

- `rebalanced` 应该替代 `refined` 成为当前主候选
- 机制创新先保留为研究方向，不急着进正式版本

## 9. 验证情况

本轮已运行：

- `pytest tests/test_v71_live.py`
- `py_compile src/btc_regime/v71_live.py`
- live-like 标准验证
- same-basis 快校验

# Module 7 Validation Review

## 结论摘要

- 本轮 `same-basis` 与 `live-like` 复核使用的仍是 `v71_final_candidate_params.json` 与 `v71_final_candidate_execution.json`，因此与旧版 `final_candidate` 的差异主要来自 **信号引擎结构改造**，而不是参数改动。
- `main_v43` 新旧结果完全一致，说明执行口径与数据源没有漂移；`xuyujian_v71_ref` 与 `wzy final_candidate` 同时变化，说明影响来自共享的 `v71_live` 结构层。
- `wzy final_candidate` 在结构改造后明显退化：`final_equity` 由 `12309.69` 降到 `9851.53`，`Sharpe` 由 `0.3188` 降到 `0.0318`，`Calmar` 由 `0.1885` 降到 `-0.0109`。
- `xuyujian_v71_ref` 小幅改善，`Sharpe` 从 `0.4284` 升到 `0.5133`。
- 新版结构并没有把收益继续锁死在 `2020`，但它把后续年份的总体质量也一起压低了；问题从“过度依赖 2020”变成了“跨年份几乎都不够赚钱”。

## Same-Basis 关键差分

- `wzy final_candidate`:
  - `final_equity delta`: `-2458.16`
  - `sharpe delta`: `-0.2870`
  - `calmar delta`: `-0.1994`
  - `max_drawdown delta`: `-0.0382`
- `xuyujian_v71_ref`:
  - `final_equity delta`: `155.40`
  - `sharpe delta`: `0.0848`
  - `calmar delta`: `0.0699`
  - `max_drawdown delta`: `0.0366`

## Live-Like 关键观察

- 旧版 `final_candidate` 2020 年盈利 `2483.88`，新版结构后 2020 年只剩 `262.28`。
- 旧版总 PnL 为 `2309.69`，新版总 PnL 为 `-148.47`。
- 年度活跃度没有塌缩，但活跃并没有转化成收益，说明问题更像“准入过严 + 持仓许可过小 + 质量阈值还不对”。

## 收益集中度

- 旧版 top 5 盈利交易占正收益比例：`35.00%`
- 新版 top 5 盈利交易占正收益比例：`42.17%`
- 旧版 top 10% 盈利交易占正收益比例：`59.43%`
- 新版 top 10% 盈利交易占正收益比例：`63.71%`

## 判断

- 这轮模块 7 复核说明：结构改造本身并非完全错误，因为 `xuyujian_v71_ref` 没有恶化；真正的问题更像是 **当前 `final_candidate` 参数与新结构的耦合失配**。
- 换句话说，问题已经从“状态解释不够清楚”推进到了“结构开始约束真实仓位，但约束过头”。
- 因此下一步不建议回退整个结构，而建议在现有结构上做一次 **小范围结构内校准**：
  1. 放宽 `long_probe / short_probe` 的最小许可阈值
  2. 下调 `short_release` 的 block 强度，避免过度压缩空头
  3. 重新审视 `range_permission`，避免把过多低波动反弹单直接禁掉


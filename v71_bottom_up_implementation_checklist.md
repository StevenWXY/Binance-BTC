# V71 Bottom-Up Implementation Checklist

## 目标

把 [v71_bottom_up_redesign_brief.md](file:///Users/apple/Documents/Binance-BTC/Binance-BTC-wzy/v71_bottom_up_redesign_brief.md) 收敛成可执行的实现清单，并按模块顺序推进，优先做低风险、可验证的增量改造。

## 模块顺序

- [x] 模块 0：明确改造边界与验证口径
- [x] 模块 1：扩展状态输出层
- [x] 模块 2：引入 Tradability Filter
- [x] 模块 3：引入 Direction Engine 新上下文字段
- [x] 模块 4：拆分 long / short 入场资格逻辑
- [x] 模块 5：把仓位许可改成连续权限映射
- [x] 模块 6：更新诊断与回测脚本口径
- [x] 模块 7：做 walk-forward 与留出集复核

## 模块 0：改造边界与验证口径

- [x] 不推翻 `v71_live`，优先在现有骨架上增量扩展
- [x] 第一阶段不主动改变现有 `signal` 生成逻辑
- [x] 第一阶段只新增解释性状态字段，避免影响已存在验证结果的含义
- [x] 后续固定采用 `train / validation / holdout` 分层看结果，而不只看全样本

## 模块 1：扩展状态输出层

### 1.1 新增字段

- [x] `v71_daily_bias`
- [x] `v71_trigger_direction`
- [x] `v71_trend_quality_score`
- [x] `v71_tradability_score`
- [x] `v71_tradability_state`

### 1.2 实现要求

- [x] 分数字段保持有界，便于后续做阈值与仓位映射
- [x] 字段全部从当前已有指标推导，不引入未来数据
- [x] 不修改现有 `raw_signal / signal / v71_market_state` 的行为
- [x] 为后续 long / short 解耦预留足够上下文

### 1.3 验证

- [x] 增加测试，验证新字段存在
- [x] 增加测试，验证分数字段范围稳定
- [x] 增加测试，验证改动不破坏原有因果性

## 模块 2：Tradability Filter

- [x] 将 `v71_tradability_score` 从解释性字段升级为真实过滤层输入
- [x] 设计 `untradable / tradable_weak / tradable_strong` 的行为差异
- [x] 让 `range -> trend` 假突破过滤更多依赖 tradability，而不是单一固定阈值

## 模块 3：Direction Engine

- [x] 将 `daily_bias + trigger_direction + trend_quality_score` 组合成统一方向上下文
- [x] 区分“方向偏置”和“最终是否允许开仓”
- [x] 为后续报告输出更稳定的趋势质量解释字段

## 模块 4：Long / Short 解耦

- [x] 把做多模块改成 `long_continuation_module`
- [x] 把做空模块改成 `short_release_module`
- [x] 不再把 `trend_down` 作为 `trend_up` 的镜像

## 模块 5：连续权限映射

- [x] 用 `tradability_score / trend_quality_score / speed / governor` 共同决定最大信号许可
- [x] 让弱证据状态只允许小仓试探，而不是硬切换到正常趋势仓
- [x] 将 `range` 默认限制为不开新方向仓，仅保留极少量例外

## 模块 6：诊断脚本更新

- [x] 更新趋势质量报告，纳入新字段
- [x] 增加按 `tradability_state` 的交易质量拆分
- [x] 增加收益集中度与年度活跃度的固定检查

## 模块 7：复核

- [x] 运行 `pytest` 受影响子集
- [x] 重跑趋势质量报告
- [x] 重跑至少一轮代表性 same-basis / live-like 验证
- [x] 明确记录：哪些改善来自结构，哪些只是参数变化

## 当前推进说明

当前已进入模块 1。第一步先把状态输出层扩出来，让后续每一轮改造都能看见：

1. 日线偏置是什么
2. 当前 4h 触发方向是什么
3. 这段趋势有多强
4. 这段行情到底值不值得做趋势

在这些字段稳定之前，不建议直接进入：

- 收紧 `trend_down`
- 降低 `range -> trend` 假突破
- 严格限制 `range` 直接开仓

因为那样仍然容易把问题收缩成“阈值微调”，而不是结构修正。

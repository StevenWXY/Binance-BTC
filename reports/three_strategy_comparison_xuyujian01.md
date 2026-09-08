# 三策略统一回测对比

本报告记录用户指定的三个 GitHub 分支，并固定为同一回测口径。策略映射为：

| 分支 | 对外策略 | 参数文件 |
| --- | --- | --- |
| `main` | V4.3 | `configs/v4_3_params.json` |
| `xuyujian修改` | V7.1 reference | `configs/v71_reference_params.json` |
| `Binance-BTC-wzy` | V7.2 TP refined | `configs/wzy_v72_tp_refined_params.json` |

## 回测条件

- 数据：`D:\文档\桌面\data.zip`，解包后的 `data/raw`；窗口 `2020-01-01` 至 `2026-08-01` UTC。
- 标的：Binance USD-M `BTCUSDT` 永续；4h 生成信号，1m 成交、标记价格和资金费。
- 初始资金：10,000 USDT。
- 执行：taker 4 bps、基础滑点 1 bps、冲击 8 bps、分钟参与率 2%、强平费 50 bps；maker 0.2 bps、报价偏移 0.5 bps、挂单超时 60 分钟。
- 账户 Governor：回撤 8%/12%/16% 时仓位缩放 0.8/0.5/0，并启用恢复重入；所有信号只使用已完成 K 线。

## 统一结果

以下结果来自 wzy 分支的 same-basis minute replay，并以本次 `data.zip` 解包数据作为复现数据源：

| 策略 | 期末权益 | 总收益 | CAGR | 年化波动 | Sharpe | Sortino | Calmar | 最大回撤 | 手续费 | 资金费 | Maker 成交率 | 强平 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| V4.3 (`main`) | 45,280.87 | 352.81% | 25.79% | 23.22% | 1.1053 | 1.9640 | 1.3481 | -19.13% | 2,865.21 | 4,785.85 | 56.13% | 0 |
| V7.1 (`xuyujian`) | 18,799.82 | 87.998% | 10.07% | 17.79% | 0.6294 | 1.0176 | 0.4365 | -23.06% | 613.14 | 1,127.19 | 49.84% | 0 |
| V7.2 (`wzy`) | **57,208.63** | **472.09%** | **30.34%** | 21.58% | **1.3375** | **2.4603** | **1.7671** | **-17.17%** | 4,858.20 | 2,606.35 | 76.29% | 0 |

## 策略摘要与关键参数

### V4.3（main）

V4.1 的趋势/反弹框架，叠加 maker 常规调仓、ATR 止损/止盈、跟踪止损和快速下跌保护。核心参数：`target_vol=1.075`、`max_leverage=6.5`、`trend_scale=1.25`、`rebound_scale=0.65`、`allow_short=false`、`rebalance_bars=60`、`stop_atr=2.5`、`take_profit_atr=12.0`、`trailing_atr=3.0`、`max_hold_bars=72`。

### V7.1（xuyujian修改）

以 `range/trend_up/trend_down` 三态状态机为核心，使用日线门控、4h 趋势确认、Donchian 突破和 ATR 波动率仓位；reference 配置不启用 live protection。核心参数：`target_vol=0.97`、`max_leverage=6.5`、`trend_scale=1.7`、`short_scale=0.15`、`trend_confirm_bars=2`、`trend_exit_confirm_bars=4`、`breakout_buffer_atr=0.20`、`trend_trailing_stop_atr=2.0`、`range_max_bars=18`。

### V7.2（wzy）

在 V7.1 live engine 上增加 long 初始确认缩放、连续趋势加仓、short 初始确认，以及强趋势保护和止盈距离放宽；同时保留 live protection 与 Governor。核心参数：`target_vol=0.78`、`max_leverage=6.0`、`trend_scale=1.30`、`short_scale=0.08`、`breakout_buffer_atr=0.22`、`stop_atr=1.8`、`take_profit_atr=3.2`、`trailing_stop_atr=1.65`、`long_initial_confirm_bars=3`、`long_initial_confirm_scale=0.78`、`long_continuation_add_on_scale=1.04`、`short_initial_confirm_bars=2`、`max_hold_bars=96`。

## 结论

在该统一执行和数据口径下，V7.2 的期末权益、CAGR、Sharpe、Sortino、Calmar 均最高，最大回撤也低于 V4.3 和 V7.1；V4.3 在 2020-2021 强趋势阶段仍具优势，V7.1 回撤控制较弱且收益效率最低。结果是历史回测，不构成未来收益保证；V7.2 机制更复杂，应继续做留出和扰动验证。

复现脚本：`scripts/compare_three_branches_same_basis.py`。wzy 原始验证明细：`reports/wzy/validations/initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01/same_basis/`。

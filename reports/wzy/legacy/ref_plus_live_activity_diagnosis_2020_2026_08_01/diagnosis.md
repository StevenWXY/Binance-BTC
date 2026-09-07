# ref_plus_live 活跃度诊断

## 核心结论

- 最后一笔 fill 之后仍有 `1055` 次信号变化，说明信号层没有休眠。
- 账户级 governor 相对峰值回撤约 `16.15%`，已达到 level 3 (`16.00%`)，当前对新的多空开仓都会返回 `0.0`。
- 诊断显示 `signal` 每年都非零，但执行层 fills/trades 只出现在 `2020`。

## 按年份的信号活跃度

 year  bars  nonzero_signal_bars  raw_signal_bars  signal_change_bars  raw_change_bars  mean_abs_signal  max_abs_signal
 2020  2196                  709              850                 247              225         0.374977        6.000000
 2021  2190                  606              771                 164              131         0.155381        2.734731
 2022  2190                  735              859                 159              136         0.181304        3.828813
 2023  2190                  704              833                 186              162         0.567638        6.000000
 2024  2196                  720              870                 233              205         0.475686        4.136281
 2025  2190                  610              721                 165              149         0.387105        5.178014
 2026  1272                  367              432                  83               73         0.295581        4.788073

## 按年份的执行活跃度

 year  fill_count  trade_count  maker_fill_count  taker_fill_count
 2020         217           74               112               105

## Governor 诊断

- `governor_peak_equity`: `14984.21`
- `equity_last_close`: `12564.56`
- `implied_drawdown_vs_governor_peak`: `16.15%`
- `scale_at_last_equity`: `0.00`
- `freeze_risk`: `True`

## 最后一笔 fill 之后

- `last_fill_time`: `2020-11-07T16:25:00+00:00`
- `bars_after_last_fill`: `12553`
- `nonzero_signal_bars_after_last_fill`: `3872`
- `signal_change_bars_after_last_fill`: `1055`


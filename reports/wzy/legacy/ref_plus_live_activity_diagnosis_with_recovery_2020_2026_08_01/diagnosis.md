# ref_plus_live 活跃度诊断

## 核心结论

- 账户级 governor 末期仍处于 level 3 区间，但恢复机制允许在 flat `10080` 分钟后，以最多 `0.25` 的 probe 重新开仓。
- 恢复机制开启后，执行层已重新覆盖多年活跃度：`2020` 到 `2026` 都有 fills/trades。

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
 2020         231           79               121               110
 2021          64           30                34                30
 2022          92           45                47                45
 2023          69           31                37                32
 2024          85           42                43                42
 2025          98           49                49                49
 2026          51           25                25                26

## Governor 诊断

- `governor_peak_equity`: `14984.21`
- `equity_last_close`: `12309.69`
- `implied_drawdown_vs_governor_peak`: `17.85%`
- `scale_at_last_equity`: `0.00`
- `freeze_risk`: `True`
- `recovery_enabled`: `True`
- `hypothetical_new_long_signal_after_recovery_cooldown`: `0.25`

## 最后一笔 fill 之后

- `last_fill_time`: `2026-07-23T07:11:00+00:00`
- `bars_after_last_fill`: `52`
- `nonzero_signal_bars_after_last_fill`: `0`
- `signal_change_bars_after_last_fill`: `0`


# 趋势判断质量报告

## 结论摘要

- `trend_up` 6-bar 平均收益 `0.65%`，命中率 `54.23%`；`trend_down` 6-bar 平均收益 `-0.04%`，命中率 `49.37%`。
- `range` 6-bar 的“低波动命中率”是 `76.41%`，可以看出震荡识别是否真的在把低方向性区间分出来。
- `trend_up` 的 6-bar 假突破率约 `89.44%`；`trend_down` 对应值约 `93.04%`。

## State Entry 质量汇总

     state  entry_count  avg_return_3  quality_hit_rate_3  avg_return_6  quality_hit_rate_6  same_state_rate_6  avg_return_12  quality_hit_rate_12  same_state_rate_12
     range          301      0.001895            0.873754     -0.000183            0.764120           0.707641       0.005250             0.647841            0.724252
trend_down          158     -0.001453            0.500000     -0.000419            0.493671           0.810127       0.001341             0.500000            0.613924
  trend_up          142      0.005755            0.549296      0.006537            0.542254           0.838028       0.008031             0.521127            0.669014

## 年度 State Entry 质量（6-bar）

 year      state  entry_count  avg_return_6  quality_hit_rate_6
 2020      range           42      0.007147            0.761905
 2020 trend_down           15      0.002449            0.466667
 2020   trend_up           27      0.008531            0.592593
 2021      range           39     -0.005247            0.435897
 2021 trend_down           23     -0.000893            0.478261
 2021   trend_up           15      0.030807            0.533333
 2022      range           51     -0.005356            0.745098
 2022 trend_down           33     -0.006235            0.606061
 2022   trend_up           18     -0.001501            0.555556
 2023      range           36      0.006686            0.916667
 2023 trend_down           17      0.004506            0.352941
 2023   trend_up           19      0.003282            0.578947
 2024      range           51     -0.002424            0.803922
 2024 trend_down           21     -0.001345            0.571429
 2024   trend_up           30      0.002402            0.500000
 2025      range           52      0.001011            0.807692
 2025 trend_down           31     -0.000568            0.548387
 2025   trend_up           21      0.002063            0.523810
 2026      range           30     -0.001565            0.900000
 2026 trend_down           18      0.005142            0.277778
 2026   trend_up           12      0.007091            0.500000

## 年度 State 分布

 year      state  bar_count    share
 2020      range       1207 0.549636
 2020 trend_down        236 0.107468
 2020   trend_up        634 0.288707
 2020     warmup        119 0.054189
 2021      range       1347 0.615068
 2021 trend_down        384 0.175342
 2021   trend_up        459 0.209589
 2022      range       1304 0.595434
 2022 trend_down        648 0.295890
 2022   trend_up        238 0.108676
 2023      range       1288 0.588128
 2023 trend_down        278 0.126941
 2023   trend_up        624 0.284932
 2024      range       1266 0.576503
 2024 trend_down        327 0.148907
 2024   trend_up        603 0.274590
 2025      range       1421 0.648858
 2025 trend_down        415 0.189498
 2025   trend_up        354 0.161644
 2026      range        793 0.623428
 2026 trend_down        323 0.253931
 2026   trend_up        156 0.122642

## 多空交易质量

 side  trade_count  win_rate   total_pnl   avg_pnl  median_pnl
 long          162  0.444444 2568.998809 15.858017   -7.559742
short          119  0.369748 -268.318873 -2.254780   -3.618073

## 年度多空交易质量

 entry_year  side  trade_count  win_rate   total_pnl    avg_pnl
       2020  long           62  0.467742 2572.169565  41.486606
       2020 short           21  0.285714 -152.396982  -7.256999
       2021  long           13  0.461538 -334.114199 -25.701092
       2021 short           14  0.428571   36.894994   2.635357
       2022  long            8  0.250000 -148.166022 -18.520753
       2022 short           29  0.310345 -172.038055  -5.932347
       2023  long           21  0.428571  289.699693  13.795223
       2023 short            9  0.222222  -65.540569  -7.282285
       2024  long           28  0.392857  -50.916798  -1.818457
       2024 short            8  0.250000    5.821138   0.727642
       2025  long           23  0.478261  288.444507  12.541066
       2025 short           24  0.458333  -10.600667  -0.441694
       2026  long            7  0.571429  -48.117937  -6.873991
       2026 short           14  0.571429   89.541269   6.395805

## 按入场 State 的交易质量

v71_market_state  side  trade_count  win_rate   total_pnl    avg_pnl
           range  long            8  0.250000 -157.817008 -19.727126
           range short            2  0.500000  -39.732723 -19.866361
      trend_down short          117  0.367521 -228.586150  -1.953728
        trend_up  long          154  0.454545 2726.815817  17.706596

## 按 Tradability State 的交易质量

v71_tradability_state  side  trade_count  win_rate   total_pnl   avg_pnl
      tradable_strong  long          140  0.450000 2420.907932 17.292200
      tradable_strong short          105  0.371429 -148.562101 -1.414877
        tradable_weak  long           21  0.380952  137.938631  6.568506
        tradable_weak short           14  0.357143 -119.756772 -8.554055
           untradable  long            1  1.000000   10.152246 10.152246

## 按 Direction Context 的交易质量

   v71_direction_context  side  trade_count  win_rate   total_pnl    avg_pnl
 long_blocked_untradable  long            1  1.000000   10.152246  10.152246
       long_continuation  long          113  0.477876 3446.417486  30.499270
              long_probe  long           44  0.340909 -868.693682 -19.743038
            neutral_wait  long            1  0.000000  -19.157027 -19.157027
            neutral_wait short            1  1.000000    1.350294   1.350294
           range_rebound  long            1  1.000000    0.273487   0.273487
short_blocked_daily_bias  long            1  1.000000    0.610301   0.610301
short_blocked_daily_bias short            1  0.000000   -0.878249  -0.878249
             short_probe short           26  0.269231 -326.445133 -12.555582
           short_release  long            1  0.000000   -0.604001  -0.604001
           short_release short           91  0.395604   57.654216   0.633563


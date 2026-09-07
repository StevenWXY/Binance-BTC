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

 side  trade_count  win_rate   total_pnl  avg_pnl  median_pnl
 long          178  0.432584 1296.550078 7.283989   -8.111055
short          123  0.414634 1013.141778 8.236925   -2.911052

## 年度多空交易质量

 entry_year  side  trade_count  win_rate   total_pnl    avg_pnl
       2020  long           59  0.491525 2663.633308  45.146327
       2020 short           20  0.250000 -179.749139  -8.987457
       2021  long           15  0.266667 -465.556653 -31.037110
       2021 short           15  0.466667  -33.052129  -2.203475
       2022  long           15  0.333333 -653.046368 -43.536425
       2022 short           30  0.433333 1109.296631  36.976554
       2023  long           21  0.571429   41.814955   1.991188
       2023 short           10  0.300000  -57.596446  -5.759645
       2024  long           29  0.413793 -364.357903 -12.564066
       2024 short           13  0.461538  124.960243   9.612326
       2025  long           29  0.379310  -30.577867  -1.054409
       2025 short           20  0.500000   17.842817   0.892141
       2026  long           10  0.400000  104.640606  10.464061
       2026 short           15  0.466667   31.439800   2.095987

## 按入场 State 的交易质量

v71_market_state  side  trade_count  win_rate   total_pnl   avg_pnl
           range  long           12  0.333333  -14.277974 -1.189831
           range short            4  0.750000    9.003512  2.250878
      trend_down short          119  0.403361 1004.138265  8.438137
        trend_up  long          166  0.439759 1310.828052  7.896555

## 按 Tradability State 的交易质量

v71_tradability_state  side  trade_count  win_rate   total_pnl   avg_pnl
      tradable_strong  long          153  0.411765  668.396807  4.368607
      tradable_strong short          105  0.400000 1156.998468 11.019033
        tradable_weak  long           23  0.521739  626.107733 27.222075
        tradable_weak short           18  0.500000 -143.856691 -7.992038
           untradable  long            2  1.000000    2.045539  1.022770

## 按 Direction Context 的交易质量

   v71_direction_context  side  trade_count  win_rate   total_pnl    avg_pnl
 long_blocked_daily_bias  long           18  0.444444   15.116209   0.839789
 long_blocked_untradable  long            1  1.000000    1.355559   1.355559
       long_continuation  long          111  0.441441 1730.931304  15.593976
              long_probe  long           44  0.386364 -395.474486  -8.988056
            neutral_wait short            1  1.000000    7.511177   7.511177
           range_rebound  long            1  1.000000    0.689981   0.689981
              range_wait  long            1  0.000000  -55.233948 -55.233948
              range_wait short            2  1.000000   10.505133   5.252566
short_blocked_daily_bias short            1  0.000000   -0.878249  -0.878249
             short_probe  long            1  1.000000    0.373489   0.373489
             short_probe short           52  0.403846  266.036434   5.116085
           short_release  long            1  0.000000   -1.208028  -1.208028
           short_release short           67  0.402985  729.967282  10.895034


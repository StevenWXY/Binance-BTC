# V7.1 / V7.2 branch audit

本目录记录 2026-09-07 至 2026-09-08 的分析与 17 组回测，使用固定源码提交，结果不是对后续分支更新的重新评估。

- [三分支差异分析](analysis_zh.md)：原生实现、WZY 参考实现与执行配置的差异。
- [V7.2 执行配置补测与策略选择](v72_execution_and_selection_2026_09_08.md)：五组补测与 V4/V7 候选比较。
- [完整指标](replay_summary.csv)：17 组案例的指标。
- [原报告复现核验](archived_result_checks.json)：六组历史报告的数值匹配。
- [数据清单](data_manifest.json)：固定提交、运行环境和输入 ZIP 的 SHA256。
- `runs/<case>/`：每组实际执行配置、权益、成交和交易记录。

冻结提交：main=`4bf42f5`、xuyujian修改=`512e46d`、Binance-BTC-wzy=`98175ae`。统一窗口为 `[2020-01-01, 2026-08-01)`，初始资金 10,000 USDT。

## 复现

需要 Python 3.12+、项目依赖，以及本地 Binance 4h、1m trade/mark 和资金费月度 ZIP，默认位置为仓库的 `data/raw`。输入数据不随报告发布。先获取远程分支以确保三个冻结提交都存在：

```sh
git fetch origin
python3 reports/branch_v71_audit_2026_09_07/audit.py --prepare
```

`--prepare` 会从 Git 提交恢复 `sources/`，并生成本地市场、资金费和信号 pickle 缓存。这些可重建文件不提交；只加载自己生成的 pickle。两份分析文档引用的 `sources/` 路径在完成这一步后可用。

运行全部案例并汇总：

```sh
python3 reports/branch_v71_audit_2026_09_07/audit.py --cases x_native x_native_rebate30 x_original_wzy_engine_native_execution x_ref_native_execution x_original_wzy_execution_no_governor x_original_wzy_execution x_ref_wzy_execution wzy_live_current wzy_v72_current main_native_rebate30 main_wzy_execution_no_governor main_wzy_execution wzy_v72_x_native wzy_v72_x_native_rebate30 wzy_v72_family_execution wzy_v72_no_governor wzy_v72_wzy_maker_soft_governor
python3 reports/branch_v71_audit_2026_09_07/audit.py --summarize
python3 reports/branch_v71_audit_2026_09_07/summarize_v72_execution.py
```

在现有目录运行会更新对应审计产物。自定义数据路径可通过 `audit.py --raw-dir` 指定；补充汇总的哈希核验默认使用仓库 `data/raw`。报告中的历史绝对路径只是当时运行的来源记录。

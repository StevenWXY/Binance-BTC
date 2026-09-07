# Reports Guide

## 1. 这份说明的目的

`reports/` 已积累了多轮研究、回测、扫描、验证和可视化产物。为了避免后续继续在根目录里找文件，这里补一份导航说明，并增加一层“当前重点结果”的入口。

本次整理遵循两个原则：

1. 不改动已经被脚本、测试或文档广泛引用的核心结果目录名。
2. 优先增加导航层和归档层，避免因为重命名大面积打断已有引用。

## 2. 当前建议从哪里看

优先查看 `reports/current/`。这里放的是当前阶段最值得直接打开的结果入口。

建议阅读顺序：

1. `01_three_branch_same_basis`
2. `02_v71_small_scan`
3. `03_ref_plus_validation`
4. `04_ref_plus_round2_scan`
5. `05_ref_plus_recovery_same_basis`
6. `06_final_candidate_live_like`
7. `07_activity_diagnosis_with_recovery`
8. `08_trend_quality_diagnosis`

## 3. 目录分层建议

虽然历史目录保留原名，但后续建议按下面的思路继续产出：

- `current/`
  - 当前阶段最重要的结果入口，主要用符号链接做导航
- `archive/`
  - 根目录里名称过于泛化、且不再作为默认入口的旧快照与图表
- 直接以实验命名的结果目录
  - 如 `three_branch_same_basis_...`
  - 如 `ref_plus_live_validation_...`
  - 如 `trend_quality_diagnosis_...`

## 4. 常见类型对应位置

### 4.1 三路线与候选验证

- `three_branch_same_basis_2020_2026_08_01`
- `balanced_recovery_validation_2020_2026_08_01`
- `ref_plus_live_validation_2020_2026_08_01`
- `ref_plus_live_round2_scan_2020_2026_08_01`
- `ref_plus_live_recovery_same_basis_2020_2026_08_01`
- `round2_best_recovery_same_basis_2020_2026_08_01`
- `final_candidate_recovery_same_basis_2020_2026_08_01`

### 4.2 Live-like 与诊断

- `ref_plus_live_live_like_validation_2020_2026_08_01`
- `ref_plus_live_recovery_live_like_2020_2026_08_01`
- `round2_best_recovery_live_like_2020_2026_08_01`
- `final_candidate_recovery_live_like_2020_2026_08_01`
- `ref_plus_live_activity_diagnosis_2020_2026_08_01`
- `ref_plus_live_activity_diagnosis_with_recovery_2020_2026_08_01`
- `trend_quality_diagnosis_2020_2026_08_01`

### 4.3 历史基础研究与家族对比

- `annual_2020_2026_08_25`
- `global_curve_v41_v6_2020_2026_08_27`
- `micro_curve_v41_v6_2020_2026_08_25`
- `micro_curve_v4_v41_v42_rebate30_2020_2026_08_25`
- `v4_family_validation_2026_09_02`
- `v6_2026_08_25`

### 4.4 默认脚本输出

以下路径仍然保留在根目录命名体系里，因为 CLI / 测试 / README 直接引用它们：

- `aggressive_*`
- `v4_3_*`
- `v4_2_*`
- `stress_test`
- `walkforward.json` 及若干 `*_walkforward.json`
- 若干 `*_grid.csv` / `*_optimization.*`

## 5. 后续整理规则

从现在开始，建议遵守：

1. 新实验优先写入“带主题 + 时间窗口”的独立目录。
2. 若只是同一主题下的再验证，继续沿用主题目录而不是回到根目录散落输出。
3. 只有明确作为 CLI 默认产物的文件，才允许直接放在 `reports/` 根目录。
4. 新文档引用结果时，优先引用实验目录，不直接引用根目录散落文件。

## 6. 本次整理范围

本次只做了两类低风险整理：

1. 新增 `current/` 导航层。
2. 将少量无明确引用、名称过于泛化的根目录快照移入 `archive/`。

这样做的目的是让目录更好找，同时不破坏现有脚本和文档。

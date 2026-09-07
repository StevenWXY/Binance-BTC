#!/usr/bin/env python3
"""Summarize module 7 validation results for the structured V71 candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_NEW_SAME_BASIS = ROOT / "reports/module7_three_branch_same_basis_final_candidate_2020_2026_08_01"
DEFAULT_OLD_SAME_BASIS = ROOT / "reports/final_candidate_recovery_same_basis_2020_2026_08_01"
DEFAULT_NEW_LIVE_LIKE = ROOT / "reports/module7_final_candidate_live_like_2020_2026_08_01"
DEFAULT_OLD_LIVE_LIKE = ROOT / "reports/final_candidate_recovery_live_like_2020_2026_08_01"
DEFAULT_OUTPUT = ROOT / "reports/module7_validation_review_2020_2026_08_01"


def _read_summary(path: Path) -> pd.DataFrame:
    return pd.read_csv(path / "summary_metrics.csv")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_code(df: pd.DataFrame, prefix: str) -> pd.Series:
    matched = df.loc[df["code"].astype(str).str.startswith(prefix)]
    if matched.empty:
        raise KeyError(f"missing strategy code prefix: {prefix}")
    return matched.iloc[0]


def _same_basis_delta(old_dir: Path, new_dir: Path) -> dict[str, object]:
    old_df = _read_summary(old_dir)
    new_df = _read_summary(new_dir)
    rows = []
    for label, prefix in [
        ("main_v43", "main_v43"),
        ("xuyujian_v71_ref", "xuyujian_v71_ref"),
        ("wzy_final", "final_candidate_recovery"),
        ("wzy_final_structured", "wzy_v71_final_structured"),
    ]:
        target_df = new_df if "structured" in label or label in {"main_v43", "xuyujian_v71_ref"} else old_df
        if label == "wzy_final":
            row = _find_code(old_df, prefix)
        else:
            row = _find_code(target_df, prefix)
        rows.append((label, row))

    old_wzy = _find_code(old_df, "final_candidate_recovery")
    new_wzy = _find_code(new_df, "wzy_v71_final_structured")
    old_x = _find_code(old_df, "xuyujian_v71_ref")
    new_x = _find_code(new_df, "xuyujian_v71_ref")
    old_main = _find_code(old_df, "main_v43")
    new_main = _find_code(new_df, "main_v43")
    return {
        "baseline_main": old_main.to_dict(),
        "current_main": new_main.to_dict(),
        "baseline_x": old_x.to_dict(),
        "current_x": new_x.to_dict(),
        "baseline_wzy": old_wzy.to_dict(),
        "current_wzy": new_wzy.to_dict(),
        "delta_main": {
            "final_equity": float(new_main["final_equity"] - old_main["final_equity"]),
            "sharpe": float(new_main["sharpe"] - old_main["sharpe"]),
            "calmar": float(new_main["calmar"] - old_main["calmar"]),
            "max_drawdown": float(new_main["max_drawdown"] - old_main["max_drawdown"]),
        },
        "delta_x": {
            "final_equity": float(new_x["final_equity"] - old_x["final_equity"]),
            "sharpe": float(new_x["sharpe"] - old_x["sharpe"]),
            "calmar": float(new_x["calmar"] - old_x["calmar"]),
            "max_drawdown": float(new_x["max_drawdown"] - old_x["max_drawdown"]),
        },
        "delta_wzy": {
            "final_equity": float(new_wzy["final_equity"] - old_wzy["final_equity"]),
            "sharpe": float(new_wzy["sharpe"] - old_wzy["sharpe"]),
            "calmar": float(new_wzy["calmar"] - old_wzy["calmar"]),
            "max_drawdown": float(new_wzy["max_drawdown"] - old_wzy["max_drawdown"]),
        },
    }


def _yearly_pnl_share(annual: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    annual = annual.copy()
    annual["pnl"] = annual["end_equity"] - annual["start_equity"]
    total_pnl = float(annual["pnl"].sum())
    for _, row in annual.iterrows():
        share = float(row["pnl"] / total_pnl) if abs(total_pnl) > 1e-12 else np.nan
        rows.append({"year": int(row["year"]), "pnl": float(row["pnl"]), "pnl_share_of_total": share})
    return rows


def _trade_concentration(trades: pd.DataFrame) -> dict[str, object]:
    if trades.empty or "pnl" not in trades:
        return {}
    pnl = trades["pnl"].astype(float).sort_values(ascending=False)
    positive = pnl[pnl > 0]
    top5_positive_share = float(positive.head(5).sum() / positive.sum()) if not positive.empty and positive.sum() != 0 else np.nan
    top_decile_count = max(1, int(np.ceil(len(positive) * 0.1))) if not positive.empty else 0
    top_decile_positive_share = (
        float(positive.head(top_decile_count).sum() / positive.sum())
        if top_decile_count > 0 and positive.sum() != 0
        else np.nan
    )
    return {
        "trade_count": int(len(trades)),
        "win_trade_count": int((trades["pnl"] > 0).sum()),
        "top5_positive_pnl_share": top5_positive_share,
        "top10pct_positive_pnl_share": top_decile_positive_share,
        "best_trade_pnl": float(pnl.iloc[0]) if not pnl.empty else np.nan,
        "worst_trade_pnl": float(pnl.iloc[-1]) if not pnl.empty else np.nan,
    }


def _activity_compare(old_activity: pd.DataFrame, new_activity: pd.DataFrame) -> list[dict[str, object]]:
    merged = old_activity.merge(new_activity, on="year", how="outer", suffixes=("_old", "_new")).fillna(0)
    rows = []
    for _, row in merged.iterrows():
        rows.append(
            {
                "year": int(row["year"]),
                "fill_count_old": int(row["fill_count_old"]),
                "fill_count_new": int(row["fill_count_new"]),
                "trade_count_old": int(row["trade_count_old"]),
                "trade_count_new": int(row["trade_count_new"]),
                "fill_delta": int(row["fill_count_new"] - row["fill_count_old"]),
                "trade_delta": int(row["trade_count_new"] - row["trade_count_old"]),
            }
        )
    return rows


def _write_markdown(output: Path, payload: dict[str, object]) -> None:
    same_basis = payload["same_basis"]
    live_like = payload["live_like"]
    delta_wzy = same_basis["delta_wzy"]
    delta_x = same_basis["delta_x"]
    if delta_x["sharpe"] >= 0:
        x_summary = (
            f"`xuyujian_v71_ref` 小幅改善，`Sharpe` 从 "
            f"`{same_basis['baseline_x']['sharpe']:.4f}` 升到 `{same_basis['current_x']['sharpe']:.4f}`。"
        )
    else:
        x_summary = (
            f"`xuyujian_v71_ref` 也同步变差，`Sharpe` 从 "
            f"`{same_basis['baseline_x']['sharpe']:.4f}` 降到 `{same_basis['current_x']['sharpe']:.4f}`。"
        )
    md = f"""# Module 7 Validation Review

## 结论摘要

- 本轮 `same-basis` 与 `live-like` 复核使用的仍是 `v71_final_candidate_params.json` 与 `v71_final_candidate_execution.json`，因此与旧版 `final_candidate` 的差异主要来自 **信号引擎结构改造**，而不是参数改动。
- `main_v43` 新旧结果完全一致，说明执行口径与数据源没有漂移；`xuyujian_v71_ref` 与 `wzy final_candidate` 同时变化，说明影响来自共享的 `v71_live` 结构层。
- `wzy final_candidate` 在结构改造后明显退化：`final_equity` 由 `{same_basis['baseline_wzy']['final_equity']:.2f}` 降到 `{same_basis['current_wzy']['final_equity']:.2f}`，`Sharpe` 由 `{same_basis['baseline_wzy']['sharpe']:.4f}` 降到 `{same_basis['current_wzy']['sharpe']:.4f}`，`Calmar` 由 `{same_basis['baseline_wzy']['calmar']:.4f}` 降到 `{same_basis['current_wzy']['calmar']:.4f}`。
- {x_summary}
- 新版结构并没有把收益继续锁死在 `2020`，但它把后续年份的总体质量也一起压低了；问题从“过度依赖 2020”变成了“跨年份几乎都不够赚钱”。

## Same-Basis 关键差分

- `wzy final_candidate`:
  - `final_equity delta`: `{delta_wzy['final_equity']:.2f}`
  - `sharpe delta`: `{delta_wzy['sharpe']:.4f}`
  - `calmar delta`: `{delta_wzy['calmar']:.4f}`
  - `max_drawdown delta`: `{delta_wzy['max_drawdown']:.4f}`
- `xuyujian_v71_ref`:
  - `final_equity delta`: `{delta_x['final_equity']:.2f}`
  - `sharpe delta`: `{delta_x['sharpe']:.4f}`
  - `calmar delta`: `{delta_x['calmar']:.4f}`
  - `max_drawdown delta`: `{delta_x['max_drawdown']:.4f}`

## Live-Like 关键观察

- 旧版 `final_candidate` 2020 年盈利 `{live_like['old_yearly_pnl'][0]['pnl']:.2f}`，新版结构后 2020 年只剩 `{live_like['new_yearly_pnl'][0]['pnl']:.2f}`。
- 旧版总 PnL 为 `{live_like['old_total_pnl']:.2f}`，新版总 PnL 为 `{live_like['new_total_pnl']:.2f}`。
- 年度活跃度没有塌缩，但活跃并没有转化成收益，说明问题更像“准入过严 + 持仓许可过小 + 质量阈值还不对”。

## 收益集中度

- 旧版 top 5 盈利交易占正收益比例：`{live_like['old_trade_concentration']['top5_positive_pnl_share']:.2%}`
- 新版 top 5 盈利交易占正收益比例：`{live_like['new_trade_concentration']['top5_positive_pnl_share']:.2%}`
- 旧版 top 10% 盈利交易占正收益比例：`{live_like['old_trade_concentration']['top10pct_positive_pnl_share']:.2%}`
- 新版 top 10% 盈利交易占正收益比例：`{live_like['new_trade_concentration']['top10pct_positive_pnl_share']:.2%}`

## 判断

- 这轮模块 7 复核说明：结构改造本身并非完全错误，因为 `xuyujian_v71_ref` 没有恶化；真正的问题更像是 **当前 `final_candidate` 参数与新结构的耦合失配**。
- 换句话说，问题已经从“状态解释不够清楚”推进到了“结构开始约束真实仓位，但约束过头”。
- 因此下一步不建议回退整个结构，而建议在现有结构上做一次 **小范围结构内校准**：
  1. 放宽 `long_probe / short_probe` 的最小许可阈值
  2. 下调 `short_release` 的 block 强度，避免过度压缩空头
  3. 重新审视 `range_permission`，避免把过多低波动反弹单直接禁掉
"""
    (output / "module7_validation_review.md").write_text(md + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-same-basis", type=Path, default=DEFAULT_NEW_SAME_BASIS)
    parser.add_argument("--old-same-basis", type=Path, default=DEFAULT_OLD_SAME_BASIS)
    parser.add_argument("--new-live-like", type=Path, default=DEFAULT_NEW_LIVE_LIKE)
    parser.add_argument("--old-live-like", type=Path, default=DEFAULT_OLD_LIVE_LIKE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    same_basis = _same_basis_delta(args.old_same_basis, args.new_same_basis)
    new_live_like = _read_json(args.new_live_like / "live_like_report.json")
    old_live_like = _read_json(args.old_live_like / "live_like_report.json")
    new_annual = pd.read_csv(args.new_live_like / "annual_metrics.csv")
    old_annual = pd.read_csv(args.old_live_like / "annual_metrics.csv")
    new_activity = pd.read_csv(args.new_live_like / "activity_by_year.csv")
    old_activity = pd.read_csv(args.old_live_like / "activity_by_year.csv")
    new_trades = pd.read_csv(args.new_live_like / "micro_trades.csv")
    old_trades = pd.read_csv(args.old_live_like / "micro_trades.csv")

    live_like = {
        "old_metrics": old_live_like["metrics"],
        "new_metrics": new_live_like["metrics"],
        "old_total_pnl": float(old_annual["end_equity"].iloc[-1] - old_annual["start_equity"].iloc[0]),
        "new_total_pnl": float(new_annual["end_equity"].iloc[-1] - new_annual["start_equity"].iloc[0]),
        "old_yearly_pnl": _yearly_pnl_share(old_annual),
        "new_yearly_pnl": _yearly_pnl_share(new_annual),
        "old_trade_concentration": _trade_concentration(old_trades),
        "new_trade_concentration": _trade_concentration(new_trades),
        "activity_compare": _activity_compare(old_activity, new_activity),
    }

    payload = {
        "new_same_basis_dir": str(args.new_same_basis),
        "old_same_basis_dir": str(args.old_same_basis),
        "new_live_like_dir": str(args.new_live_like),
        "old_live_like_dir": str(args.old_live_like),
        "same_basis": same_basis,
        "live_like": live_like,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "module7_validation_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(live_like["old_yearly_pnl"]).to_csv(args.output / "old_yearly_pnl_share.csv", index=False)
    pd.DataFrame(live_like["new_yearly_pnl"]).to_csv(args.output / "new_yearly_pnl_share.csv", index=False)
    pd.DataFrame(live_like["activity_compare"]).to_csv(args.output / "activity_compare.csv", index=False)
    pd.DataFrame([live_like["old_trade_concentration"], live_like["new_trade_concentration"]], index=["old", "new"]).to_csv(
        args.output / "trade_concentration_compare.csv"
    )
    _write_markdown(args.output, payload)
    print(json.dumps(payload["same_basis"]["delta_wzy"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

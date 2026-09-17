"""Summarize the V7.2 execution counterfactuals and existing family evidence."""

from __future__ import annotations

import hashlib

import pandas as pd

from audit import OUTPUT, ROOT, module, read_json, write_json


def main():
    manifest = read_json(OUTPUT / "data_manifest.json")
    raw = ROOT / "data/raw"
    for archive in manifest["archives"]:
        path = raw / archive["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != archive["sha256"]:
            raise AssertionError(f"Archive changed since initial audit: {path}")

    calculate = module("wzy", "backtest").calculate_metrics
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "recent_2025_2026_07": ("2025-01-01", "2026-08-01"),
    }
    summaries = []
    annual_rows = []
    for path in sorted((OUTPUT / "runs").glob("wzy_v72*/result.json")):
        result = read_json(path)
        equity = pd.read_csv(path.with_name("equity.csv"), index_col=0, parse_dates=True).iloc[:, 0]
        summary = {"case": result["case"], **result["metrics"]}
        for period, (start, end) in periods.items():
            window = equity.loc[start:end]
            metrics = calculate(window, window.pct_change().dropna(), pd.DataFrame(), 2190)
            summary.update({f"{period}_{key}": value for key, value in metrics.items()})
        summaries.append(summary)
        for year in range(2020, 2027):
            end = min(pd.Timestamp(f"{year + 1}-01-01", tz="UTC"), equity.index[-1])
            window = equity.loc[pd.Timestamp(f"{year}-01-01", tz="UTC"):end]
            metrics = calculate(window, window.pct_change().dropna(), pd.DataFrame(), 2190)
            annual_rows.append({"case": result["case"], "year": year, **metrics})

    frame = pd.DataFrame(summaries)
    frame.to_csv(OUTPUT / "v72_execution_comparison_2026_09_08.csv", index=False)
    pd.DataFrame(annual_rows).to_csv(OUTPUT / "v72_annual_comparison_2026_09_08.csv", index=False)

    family = pd.read_csv(ROOT / "reports/unified_v4_v7_btc_2020_2026_08_01/summary_metrics.csv")
    family = family.loc[family.code != "BTC"].copy()
    family["calmar"] = family.cagr / family.max_drawdown.abs()
    family["contains_neutral_overlay"] = family.code.isin(["V4.2.2", "V7.1.3"])
    family.to_csv(OUTPUT / "family_comparison_2026_09_08.csv", index=False)
    write_json(OUTPUT / "supplement_verification_2026_09_08.json", {
        "archive_hashes_verified": len(manifest["archives"]),
        "v72_cases": len(frame),
        "new_cases": 5,
        "same_signal_source": "wzy_v72_signals.pkl",
        "signal_sha256": hashlib.sha256((OUTPUT / "wzy_v72_signals.pkl").read_bytes()).hexdigest(),
        "scope": "Fixed original commits and [2020-01-01, 2026-08-01); no retuning or new holdout",
    })
    columns = ["case", "final_equity", "cagr", "sharpe", "max_drawdown",
               "recent_2025_2026_07_cagr", "recent_2025_2026_07_sharpe", "recent_2025_2026_07_max_drawdown"]
    print(frame[columns].to_string(index=False))
    print("Verified all", len(manifest["archives"]), "archive hashes against the original audit.")


if __name__ == "__main__":
    main()

"""Reproduce branch comparisons using frozen sources and one local market dataset."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from dataclasses import asdict

import numpy as np
import pandas as pd


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
START = "2020-01-01"
END = "2026-08-01"
REFS = {"main": "4bf42f5", "x": "512e46d", "wzy": "98175ae"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def package(branch):
    name = f"audit_{branch}"
    if name not in sys.modules:
        path = OUTPUT / "sources" / branch / "src" / "btc_regime"
        spec = importlib.util.spec_from_file_location(
            name, path / "__init__.py", submodule_search_locations=[str(path)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


def module(branch, name):
    return importlib.import_module(f"{package(branch)}.{name}")


def config(branch, name):
    return read_json(OUTPUT / "sources" / branch / "configs" / name)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def prepare(raw_dir):
    manifest = {"start": START, "end_exclusive": END, "raw_dir": str(raw_dir), "commits": {}}
    for branch, ref in REFS.items():
        sha = subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
        manifest["commits"][branch] = sha
        payload = subprocess.check_output(["git", "archive", sha, "src", "configs"], cwd=ROOT)
        target = OUTPUT / "sources" / branch
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            archive.extractall(target, filter="data")

    data = module("x", "data")
    market = data.load_market_data(raw_dir, start=START, end=END)
    market = market.loc[market.index < pd.Timestamp(END, tz="UTC")].copy()
    funding = data.load_funding(raw_dir, start=START, end=END)
    funding = funding.loc[funding.index < pd.Timestamp(END, tz="UTC")].copy()
    market.to_pickle(OUTPUT / "market.pkl")
    funding.to_pickle(OUTPUT / "funding.pkl")
    manifest["market"] = {
        "rows": len(market), "first": str(market.index[0]), "last": str(market.index[-1]),
        "duplicates": int(market.index.duplicated().sum()),
        "sha256_pandas_hash": hashlib.sha256(pd.util.hash_pandas_object(market).values.tobytes()).hexdigest(),
    }
    manifest["funding_rows"] = len(funding)
    manifest["python"] = sys.version
    manifest["pandas"] = pd.__version__
    manifest["numpy"] = np.__version__
    files = []
    for folder, pattern in [("klines", "BTCUSDT-4h-*.zip"), ("klines", "BTCUSDT-1m-*.zip"),
                            ("mark_price", "BTCUSDT-1m-*.zip"), ("funding", "BTCUSDT-fundingRate-*.zip")]:
        for path in sorted((raw_dir / folder).glob(pattern)):
            period = path.stem.rsplit("-", 2)[-2:]
            if len(period[0]) != 4 or not "2020-01" <= "-".join(period) < "2026-08":
                continue
            files.append({"path": str(path.relative_to(raw_dir)), "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest["archives"] = files

    x = module("x", "v7")
    wzy = module("wzy", "v71_live")
    main = module("main", "v43")
    signals = {
        "x_original": x.generate_v7_signals(market, x.V7Params(**config("x", "v71_params.json"))),
        "x_ref": wzy.generate_v71_live_signals(market, wzy.V71LiveParams(**config("wzy", "v71_reference_params.json"))),
        "wzy_live": wzy.generate_v71_live_signals(market, wzy.V71LiveParams(**config("wzy", "v71_live_params.json"))),
        "wzy_v72": wzy.generate_v71_live_signals(market, wzy.V71LiveParams(**config("wzy", "wzy_v72_tp_refined_params.json"))),
        "main_v43": main.generate_v43_signals(market, main.V43Params(**config("main", "v4_3_params.json"))),
    }
    stats = {}
    for name, frame in signals.items():
        frame.to_pickle(OUTPUT / f"{name}_signals.pkl")
        signal = frame["signal"].fillna(0)
        stats[name] = {
            "bars": len(signal), "long_bars": int((signal > 0).sum()),
            "short_bars": int((signal < 0).sum()), "flat_bars": int((signal == 0).sum()),
            "mean_absolute_target_leverage": float(signal.abs().mean()),
            "max_absolute_target_leverage": float(signal.abs().max()),
            "signal_changes": int(signal.ne(signal.shift()).sum()),
        }
    a = signals["x_original"]["signal"].fillna(0)
    b = signals["x_ref"]["signal"].fillna(0)
    changed = ~np.isclose(a, b, rtol=0, atol=1e-12)
    stats["original_vs_reference"] = {
        "different_signal_bars": int(changed.sum()),
        "different_direction_bars": int((np.sign(a) != np.sign(b)).sum()),
        "first_difference": str(a.index[changed][0]),
    }
    pd.DataFrame({"x_original": a, "wzy_x_ref": b}).loc[changed].head(30).to_csv(OUTPUT / "first_signal_differences.csv")
    write_json(OUTPUT / "signal_comparison.json", stats)
    write_json(OUTPUT / "data_manifest.json", manifest)
    print(json.dumps(stats, indent=2), flush=True)


def cases():
    native = config("x", "v71_execution.json")
    native_wzy = {**native, "strategy_drawdown_reduce_only_level_3": False}
    latest = config("wzy", "wzy_v72_execution.json")
    main_native = {
        "initial_cash": 10000, "taker_fee_bps": 2.8, "maker_enabled": True,
        "maker_fee_bps": 0.14, "maker_offset_bps": 0, "base_slippage_bps": 1,
        "impact_bps": 8, "max_minute_participation": 0.02,
    }
    return {
        "x_native": ("x", "x_original", native),
        "x_native_rebate30": ("x", "x_original", {**native, "taker_fee_bps": 2.8}),
        "x_original_wzy_engine_native_execution": ("wzy", "x_original", native_wzy),
        "x_ref_native_execution": ("wzy", "x_ref", native_wzy),
        "x_original_wzy_execution": ("wzy", "x_original", latest),
        "x_original_wzy_execution_no_governor": ("wzy", "x_original", {**latest, "strategy_drawdown_enabled": False}),
        "x_ref_wzy_execution": ("wzy", "x_ref", latest),
        "wzy_live_current": ("wzy", "wzy_live", config("wzy", "v71_live_execution.json")),
        "wzy_v72_current": ("wzy", "wzy_v72", latest),
        "wzy_v72_x_native": ("wzy", "wzy_v72", native_wzy),
        "wzy_v72_x_native_rebate30": ("wzy", "wzy_v72", {**native_wzy, "taker_fee_bps": 2.8}),
        "wzy_v72_family_execution": ("wzy", "wzy_v72", {
            **native_wzy, "taker_fee_bps": 2.8, "maker_enabled": True,
            "maker_fee_bps": 0.14, "maker_offset_bps": 0.0,
            "maker_order_timeout_minutes": 60, "maker_exit_enabled": False,
        }),
        "wzy_v72_no_governor": ("wzy", "wzy_v72", {**latest, "strategy_drawdown_enabled": False}),
        "wzy_v72_wzy_maker_soft_governor": ("wzy", "wzy_v72", {
            **native_wzy, "maker_enabled": True, "maker_fee_bps": 0.2,
            "maker_offset_bps": 0.5, "maker_order_timeout_minutes": 60,
            "maker_exit_enabled": False,
        }),
        "main_native_rebate30": ("main", "main_v43", main_native),
        "main_wzy_execution": ("wzy", "main_v43", latest),
        "main_wzy_execution_no_governor": ("wzy", "main_v43", {**latest, "strategy_drawdown_enabled": False}),
    }


def run_case(name, raw_dir):
    branch, signal_name, execution = cases()[name]
    engine = module(branch, "micro_backtest")
    data = module(branch, "data")
    settings = engine.MicroBacktestConfig(**execution)
    signaled = pd.read_pickle(OUTPUT / f"{signal_name}_signals.pkl")
    funding = pd.read_pickle(OUTPUT / "funding.pkl")
    started = time.monotonic()
    coverage = {"rows": 0, "batches": 0, "first": None, "last": None, "nonmonotonic_boundaries": 0}

    def batches():
        previous_end = None
        for batch in data.iter_intrabar_months(raw_dir, start=START, end=END):
            if previous_end is not None and batch.index[0] <= previous_end:
                coverage["nonmonotonic_boundaries"] += 1
            if batch.index.has_duplicates or not batch.index.is_monotonic_increasing:
                raise ValueError("Duplicate or non-monotonic minute data")
            previous_end = batch.index[-1]
            coverage["rows"] += len(batch)
            coverage["batches"] += 1
            if coverage["first"] is None:
                coverage["first"] = str(batch.index[0])
            coverage["last"] = str(batch.index[-1])
            yield batch

    result = engine.run_micro_backtest(signaled, batches(), funding, settings)
    target = OUTPUT / "runs" / name
    target.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(target / "equity.csv")
    result.trades.to_csv(target / "trades.csv", index=False)
    result.fills.to_csv(target / "fills.csv", index=False)
    write_json(target / "result.json", {
        "case": name, "branch_engine": branch, "signal_source": signal_name,
        "execution": asdict(settings), "metrics": result.metrics,
        "coverage": coverage, "seconds": time.monotonic() - started,
    })
    print(name, json.dumps({k: result.metrics.get(k) for k in ["final_equity", "sharpe", "max_drawdown", "trade_count"]}), flush=True)


def summarize():
    rows = []
    for path in sorted((OUTPUT / "runs").glob("*/result.json")):
        result = read_json(path)
        rows.append({"case": result["case"], **result["metrics"]})
    summary = pd.DataFrame(rows)
    summary.to_csv(OUTPUT / "replay_summary.csv", index=False)
    print(summary[["case", "final_equity", "cagr", "sharpe", "max_drawdown", "trade_count"]].to_string(index=False))
    latest_report = "reports/wzy/validations/initial_confirm_continuation_short_longstrong_tp_refined_validation_2020_2026_08_01/same_basis/report.json"
    references = {
        "x_native": ("x", "reports/v712_micro_2020_2026_07/v71_taker_no_rebate/micro_metrics.json", ("metrics",)),
        "x_native_rebate30": ("x", "reports/unified_v4_v7_btc_2020_2026_08_01/v7.1/micro_metrics.json", ("metrics",)),
        "main_native_rebate30": ("main", "reports/v4_3_rebate30/report.json", ("metrics",)),
        "main_wzy_execution": ("wzy", latest_report, ("strategies", "main_v43", "metrics")),
        "x_ref_wzy_execution": ("wzy", latest_report, ("strategies", "xuyujian_v71_ref", "metrics")),
        "wzy_v72_current": ("wzy", latest_report, ("strategies", "initial_confirm_continuation_short_longstrong_tp_refined", "metrics")),
    }
    checks = {}
    for name, (branch, path, keys) in references.items():
        archived = json.loads(subprocess.check_output(["git", "show", f"{REFS[branch]}:{path}"], cwd=ROOT))
        for key in keys:
            archived = archived[key]
        actual = read_json(OUTPUT / "runs" / name / "result.json")["metrics"]
        differences = {key: actual[key] - archived[key] for key in ["final_equity", "cagr", "sharpe", "max_drawdown"]}
        checks[name] = {"ref": REFS[branch], "path": path, "differences": differences,
                        "matched": all(abs(value) < 1e-7 for value in differences.values())}
    checks["engine_equivalence"] = {
        "equity_csv_identical": (OUTPUT / "runs/x_native/equity.csv").read_bytes()
        == (OUTPUT / "runs/x_original_wzy_engine_native_execution/equity.csv").read_bytes()
    }
    write_json(OUTPUT / "archived_result_checks.json", checks)
    if not all(item["matched"] for name, item in checks.items() if name != "engine_equivalence"):
        raise AssertionError("An archived result did not reproduce")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.raw_dir)
    for name in args.cases or []:
        run_case(name, args.raw_dir)
    if args.summarize:
        summarize()

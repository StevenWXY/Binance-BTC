#!/usr/bin/env python3
"""Compare V4.3, V7.1 and V7.2 with/without strategy drawdown control."""
from __future__ import annotations
import argparse, io, json, sys, zipfile
from dataclasses import asdict
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from btc_regime.data import load_ohlc_archive_bytes  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, micro_period_metrics, run_micro_backtest  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402

def load_from_source(source_zip: Path, start: str, end: str):
    with zipfile.ZipFile(source_zip) as source:
        market = [load_ohlc_archive_bytes(source.read(n)) for n in source.namelist()
                  if n.startswith("data/raw/klines/BTCUSDT-4h-") and n.endswith(".zip")]
        funding = []
        for n in source.namelist():
            if not (n.startswith("data/raw/funding/") and n.endswith(".zip")):
                continue
            with zipfile.ZipFile(io.BytesIO(source.read(n))) as nested:
                frame = pd.read_csv(io.BytesIO(nested.read(nested.namelist()[0])))
            frame["timestamp"] = pd.to_datetime(frame["calc_time"], unit="ms", utc=True)
            frame["funding_rate"] = pd.to_numeric(frame["last_funding_rate"], errors="coerce")
            funding.append(frame.set_index("timestamp")[["funding_rate"]])
    end_ts = pd.Timestamp(end, tz="UTC")
    market = pd.concat(market).sort_index()
    market = market.loc[(market.index >= pd.Timestamp("2020-01-01", tz="UTC")) & (market.index < end_ts)]
    funding = pd.concat(funding).sort_index()
    funding = funding.loc[(funding.index >= pd.Timestamp(start, tz="UTC")) & (funding.index < end_ts)]
    return market, funding

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-zip", type=Path, default=Path(r"D:\文档\桌面\data.zip"))
    p.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-08-01")
    p.add_argument("--output", type=Path, default=ROOT / "reports/six_strategies_drawdown_2020_2026_08_01")
    a = p.parse_args()
    market, funding = load_from_source(a.source_zip, a.start, a.end)
    configs = {
        "v4_3": ("V4.3", V43Params, generate_v43_signals, ROOT / "configs/v4_3_params.json"),
        "v7_1": ("V7.1", V7Params, generate_v7_signals, ROOT / "configs/v71_params.json"),
        "v7_2": ("V7.2", V71LiveParams, generate_v71_live_signals, ROOT / "configs/wzy_v72_tp_refined_params.json"),
    }
    common = dict(initial_cash=10000.0, taker_fee_bps=4.0, base_slippage_bps=1.0,
                  impact_bps=8.0, max_minute_participation=0.02, liquidation_fee_bps=50.0)
    dd = dict(strategy_drawdown_enabled=True, strategy_drawdown_level_1=0.08,
              strategy_drawdown_scale_1=0.80, strategy_drawdown_level_2=0.12,
              strategy_drawdown_scale_2=0.50, strategy_drawdown_level_3=0.16,
              strategy_drawdown_scale_3=0.0)
    out = a.output; out.mkdir(parents=True, exist_ok=True)
    rows, curves, report = [], [], {"data": {"source_zip": str(a.source_zip), "start": a.start, "end": a.end}, "global_execution": common, "runs": {}}
    for key, (name, cls, generator, params_path) in configs.items():
        params = cls(**json.loads(params_path.read_text(encoding="utf-8")))
        signals = generator(market, params)
        signals = signals.loc[signals.index < pd.Timestamp(a.end, tz="UTC")]
        for suffix, control in (("no_dd", {}), ("dd_control", dd)):
            cfg = MicroBacktestConfig(**common, **control)
            batches = __import__("compare_v4_v7_micro_local").iter_local_batches(a.raw_dir, a.start, a.end, a.source_zip)
            result = run_micro_backtest(signals, batches, funding, cfg)
            m = result.metrics
            code = f"{key}_{suffix}"
            rows.append({"run": code, "strategy": name, "drawdown_control": cfg.strategy_drawdown_enabled,
                         "final_equity": m["final_equity"], "total_return": m["total_return"], "cagr": m["cagr"],
                         "annualized_volatility": m["annualized_volatility"], "sharpe": m["sharpe"],
                         "sortino": m["sortino"], "max_drawdown": m["max_drawdown"], "fees_paid": m["fees_paid"],
                         "funding_paid": m["funding_paid"], "max_leverage_observed": m.get("max_leverage_observed", 0.0),
                         "max_participation_observed": m.get("max_minute_participation_observed", 0.0),
                         "liquidation_count": m["liquidation_count"]})
            curves.append(result.equity.rename(code))
            report["runs"][code] = {"strategy": name, "params_file": str(params_path), "params": params.to_dict(),
                                    "execution": asdict(cfg), "metrics": m, "periods": micro_period_metrics(result)}
    pd.DataFrame(rows).to_csv(out / "summary_metrics.csv", index=False)
    pd.concat(curves, axis=1).to_csv(out / "equity_curves.csv")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(pd.DataFrame(rows).to_string(index=False))
if __name__ == "__main__": main()

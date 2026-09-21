"""V4.4.1 fixed-grid selection. Never loads holdout rows into candidate evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from itertools import product
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from btc_regime.v441_research import PERIODS, candidate_grid, metrics, proxy_run, select, selection_score
from btc_regime.v441 import V441Params


def save_selection(out, prefix, payload, csv_text, json_text, config_path):
    """Check frozen artifacts before writing anything, including candidate tables."""
    lock = out / ("final_selection_lock.json" if prefix else "selection_lock.json")
    if lock.exists():
        previous = json.loads(lock.read_text())
        for key in ("params", "candidate_table_sha256", "source_sha256", "protocol_sha256"):
            if previous[key] != payload[key]:
                raise RuntimeError("Selection lock differs: preserve it; use a separate research version")
        # An identical rerun must not report a new pre-holdout freeze timestamp.
        payload = previous
    else:
        lock.write_text(json.dumps(payload, indent=2) + "\n")
    (out / f"{prefix}candidates.csv").write_text(csv_text)
    (out / f"{prefix}candidates.json").write_text(json_text)
    config_path.write_text(json.dumps(payload["params"], indent=2) + "\n")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/v441"))
    parser.add_argument("--output", type=Path, default=Path("reports/v4_4_1"))
    parser.add_argument("--phase2", action="store_true")
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    cutoff = pd.Timestamp("2025-07-01", tz="UTC")
    data = pd.read_pickle(args.cache / "hourly.pkl").loc[lambda d: d.index < cutoff]
    funding = pd.read_pickle(args.cache / "funding.pkl").loc[lambda d: d.index < cutoff]
    rows = []
    candidates = candidate_grid()
    prefix = ""
    protocol_name = "protocol.json"
    if args.phase2:
        frozen = json.loads((out / "phase1/selection_lock.json").read_text())
        base = V441Params(**frozen["params"])
        candidates = [base] + [replace(base, core_scale=c, satellite_scale=s)
                                for c, s in product([.75, 1.], [.25, .5, 1.])]
        prefix = "phase2_"
        protocol_name = "phase2_protocol.json"
    for i, params in enumerate(candidates):
        parts = {}
        for name in ("legacy", "recent_train", "recent_validation"):
            result = proxy_run(data, funding, params, *PERIODS[name])
            parts[name] = metrics(result.equity, result.trades)
        row = {"id": f"{prefix}c{i:02d}", "params": params.to_dict(), "periods": parts,
               "score": selection_score(parts)}
        rows.append(row)
        print(row["id"], "score", round(row["score"], 3),
              "train/val Sharpe", [round(parts[k]["sharpe"], 2) for k in ["recent_train", "recent_validation"]],
              "cycles", [parts[k]["cycles"] for k in ["recent_train", "recent_validation"]], flush=True)
    chosen = select(rows)
    equal_era = select(rows, {"legacy": .6, "recent_train": .2, "recent_validation": .2})
    flat = []
    for r in rows:
        flat.append({"id": r["id"], **r["params"], "score": r["score"], **r["admission"],
                     "eligible": r["eligible"],
                     **{f"{k}_{m}": v for k, part in r["periods"].items() for m, v in part.items()}})
    csv_text = pd.DataFrame(flat).sort_values("score", ascending=False).to_csv(index=False)
    json_text = json.dumps(rows, indent=2) + "\n"
    payload = {"version": "V4.4.1", "selected_id": chosen["id"], "params": chosen["params"],
               "development_score": chosen["score"], "legacy_heavy_counterfactual_id": equal_era["id"],
               "development_end_exclusive": str(cutoff), "actual_periods": PERIODS,
               "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
               "protocol_sha256": hashlib.sha256((out / protocol_name).read_bytes()).hexdigest(),
               "candidate_table_sha256": hashlib.sha256(csv_text.encode()).hexdigest(),
               "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                  [Path("src/btc_regime/v441.py"), Path("src/btc_regime/v441_research.py"),
                                   Path("src/btc_regime/micro_backtest.py")]},
               "holdout_used_for_selection": False}
    payload = save_selection(out, prefix, payload, csv_text, json_text,
                             Path("configs/v4_4_1_params.json"))
    print("FROZEN", json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()

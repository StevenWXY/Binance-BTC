#!/usr/bin/env python3
"""Run full-sample same-basis comparison and stress validation for one V71 candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.micro_backtest import MicroBacktestConfig  # noqa: E402
from btc_regime.stress import run_stress_suite, write_stress_report  # noqa: E402


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, help="candidate short name")
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument(
        "--output",
        type=Path,
        help="output directory; defaults to reports/<candidate>_validation_2020_2026_08_01",
    )
    parser.add_argument("--stress-bars", type=int, default=420)
    parser.add_argument("--stress-seed", type=int, default=7)
    parser.add_argument("--stress-repeats", type=int, default=2)
    parser.add_argument("--stress-minutes-per-bar", type=int, default=240)
    args = parser.parse_args()

    output = args.output or ROOT / f"reports/{args.candidate}_validation_2020_2026_08_01"
    compare_output = output / "same_basis"
    stress_output = output / "stress"
    output.mkdir(parents=True, exist_ok=True)

    compare_cmd = [
        str(ROOT / ".venv" / "bin" / "python"),
        str(ROOT / "scripts" / "compare_three_branches_same_basis.py"),
        "--raw-dir",
        str(args.raw_dir),
        "--start",
        args.start,
        "--end",
        args.end,
        "--execution",
        str(args.execution),
        "--wzy-params",
        str(args.params),
        "--wzy-code",
        args.candidate,
        "--wzy-name",
        f"wzy: {args.candidate}",
        "--output",
        str(compare_output),
    ]
    subprocess.run(compare_cmd, check=True, cwd=ROOT)

    stress_result = run_stress_suite(
        _read_json(args.params),
        engine="v71_live",
        bars=args.stress_bars,
        seed=args.stress_seed,
        repeats=args.stress_repeats,
        minutes_per_bar=args.stress_minutes_per_bar,
        micro_config=MicroBacktestConfig(**_read_json(args.execution)),
    )
    write_stress_report(stress_result, stress_output)

    summary = {
        "candidate": args.candidate,
        "params_file": str(args.params),
        "execution_file": str(args.execution),
        "same_basis_report": str(compare_output / "report.json"),
        "same_basis_summary": str(compare_output / "summary_metrics.csv"),
        "stress_report": str(stress_output / "stress_report.json"),
        "stress_summary": str(stress_output / "stress_summary.csv"),
        "stress_metadata": stress_result.metadata,
    }
    (output / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

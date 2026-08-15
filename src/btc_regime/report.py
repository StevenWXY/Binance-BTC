"""CSV/JSON/PNG report generation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .backtest import BacktestResult
from .strategy import StrategyParams


def write_report(result: BacktestResult, params: StrategyParams, output_dir: str | Path, label: str) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / f"{label}_metrics.json").open("w", encoding="utf-8") as handle:
        json.dump({"strategy": params.to_dict(), "metrics": result.metrics}, handle, indent=2)
    result.equity.to_csv(output / f"{label}_equity.csv", header=True)
    result.trades.to_csv(output / f"{label}_trades.csv", index=False)
    # Plotting is optional so headless data/optimization runs need only pandas.
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(12, 5))
    result.equity.plot(ax=ax, color="#1d4ed8", lw=1.2)
    ax.set_title(f"BTCUSDT USD-M perpetual | {label}")
    ax.set_ylabel("Equity (USDT)")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output / f"{label}_equity.png", dpi=150)
    plt.close(fig)

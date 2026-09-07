#!/usr/bin/env python3
"""Diagnose ref_plus_live signal and execution activity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.live_risk import AccountDrawdownGovernor  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/ref_plus_live_activity_diagnosis_2020_2026_08_01"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_market(raw_dir: Path, start: str, end: str) -> pd.DataFrame:
    requested_start = pd.Timestamp(start, tz="UTC")
    load_start = "2020-01-01" if requested_start > pd.Timestamp("2020-01-01", tz="UTC") else start
    return load_market_data(raw_dir, start=load_start, end=end)


def _yearly_signal_activity(signaled: pd.DataFrame) -> pd.DataFrame:
    frame = signaled.copy()
    frame["year"] = frame.index.year
    frame["signal_change"] = frame["signal"].diff().abs().fillna(frame["signal"].abs()) > 1e-12
    frame["raw_change"] = frame["raw_signal"].diff().abs().fillna(frame["raw_signal"].abs()) > 1e-12
    return frame.groupby("year").agg(
        bars=("signal", "size"),
        nonzero_signal_bars=("signal", lambda s: int((s.abs() > 1e-12).sum())),
        raw_signal_bars=("raw_signal", lambda s: int((s.abs() > 1e-12).sum())),
        signal_change_bars=("signal_change", lambda s: int(s.sum())),
        raw_change_bars=("raw_change", lambda s: int(s.sum())),
        mean_abs_signal=("signal", lambda s: float(s.abs().mean())),
        max_abs_signal=("signal", lambda s: float(s.abs().max())),
    ).reset_index()


def _yearly_execution_activity(result) -> pd.DataFrame:
    fills = result.fills.copy()
    trades = result.trades.copy()
    fill_years = set(pd.to_datetime(fills["timestamp"], utc=True).dt.year.tolist()) if not fills.empty else set()
    trade_years = set(pd.to_datetime(trades["exit_time"], utc=True).dt.year.tolist()) if not trades.empty else set()
    years = fill_years | trade_years
    rows = []
    for year in sorted(set(years)):
        fill_mask = pd.to_datetime(fills["timestamp"], utc=True).dt.year == year if not fills.empty else pd.Series([], dtype=bool)
        trade_mask = pd.to_datetime(trades["exit_time"], utc=True).dt.year == year if not trades.empty else pd.Series([], dtype=bool)
        rows.append(
            {
                "year": int(year),
                "fill_count": int(fill_mask.sum()) if not fills.empty else 0,
                "trade_count": int(trade_mask.sum()) if not trades.empty else 0,
                "maker_fill_count": int((fills.loc[fill_mask, "liquidity"] == "maker").sum()) if not fills.empty and "liquidity" in fills else 0,
                "taker_fill_count": int((fills.loc[fill_mask, "liquidity"] == "taker").sum()) if not fills.empty and "liquidity" in fills else 0,
            }
        )
    return pd.DataFrame(rows)


def _top_counts_by_year(signaled: pd.DataFrame, column: str, top_n: int = 5) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    series = signaled[column].astype(str)
    for year, sub in series.groupby(series.index.year):
        counts = sub.value_counts().head(top_n)
        total = int(len(sub))
        for label, count in counts.items():
            rows.append(
                {
                    "year": int(year),
                    "column": column,
                    "label": str(label),
                    "count": int(count),
                    "share": float(count / total) if total else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _post_last_fill_signal_activity(signaled: pd.DataFrame, result) -> dict[str, object]:
    if result.fills.empty:
        return {"last_fill_time": None, "bars_after_last_fill": 0, "signal_change_bars_after_last_fill": 0}
    last_fill_time = pd.to_datetime(result.fills["timestamp"], utc=True).max()
    after = signaled.loc[signaled.index > last_fill_time]
    signal_change = after["signal"].diff().abs().fillna(after["signal"].abs()) > 1e-12
    return {
        "last_fill_time": last_fill_time.isoformat(),
        "bars_after_last_fill": int(len(after)),
        "nonzero_signal_bars_after_last_fill": int((after["signal"].abs() > 1e-12).sum()),
        "signal_change_bars_after_last_fill": int(signal_change.sum()),
        "market_state_counts_after_last_fill": after["v71_market_state"].astype(str).value_counts().to_dict(),
        "regime_counts_after_last_fill": after["regime"].astype(str).value_counts().head(10).to_dict(),
    }


def _governor_freeze_diagnosis(
    result,
    execution: MicroBacktestConfig,
    last_fill_time: pd.Timestamp | None = None,
) -> dict[str, object]:
    governor = AccountDrawdownGovernor(
        enabled=execution.strategy_drawdown_enabled,
        level_1=execution.strategy_drawdown_level_1,
        scale_1=execution.strategy_drawdown_scale_1,
        level_2=execution.strategy_drawdown_level_2,
        scale_2=execution.strategy_drawdown_scale_2,
        level_3=execution.strategy_drawdown_level_3,
        scale_3=execution.strategy_drawdown_scale_3,
        reduce_only_level_3=execution.strategy_drawdown_reduce_only_level_3,
    )
    last_equity = float(result.equity.iloc[-1])
    implied_drawdown = 0.0
    if result.metrics.get("governor_peak_equity", 0.0) > 0:
        implied_drawdown = max(
            0.0,
            1.0 - last_equity / float(result.metrics["governor_peak_equity"]),
        )
    diagnosis = {
        "enabled": execution.strategy_drawdown_enabled,
        "recovery_enabled": execution.strategy_drawdown_recovery_enabled,
        "recovery_flat_cooldown_minutes": execution.strategy_drawdown_recovery_flat_cooldown_minutes,
        "recovery_max_signal": execution.strategy_drawdown_recovery_max_signal,
        "governor_peak_equity": float(result.metrics.get("governor_peak_equity", 0.0)),
        "equity_last_close": last_equity,
        "governor_max_drawdown_observed": float(result.metrics.get("governor_max_drawdown_observed", 0.0)),
        "implied_drawdown_vs_governor_peak": float(implied_drawdown),
        "level_3": execution.strategy_drawdown_level_3,
        "scale_at_last_equity": float(governor.scale_for_drawdown(implied_drawdown)),
        "hypothetical_new_long_signal_after_last_equity": float(governor.apply_signal(1.0, 0.0, implied_drawdown)),
        "hypothetical_new_short_signal_after_last_equity": float(governor.apply_signal(-1.0, 0.0, implied_drawdown)),
        "freeze_risk": bool(
            execution.strategy_drawdown_enabled
            and execution.strategy_drawdown_reduce_only_level_3
            and implied_drawdown >= execution.strategy_drawdown_level_3
        ),
    }
    if last_fill_time is not None and execution.strategy_drawdown_recovery_enabled:
        probe_time = last_fill_time + pd.Timedelta(minutes=execution.strategy_drawdown_recovery_flat_cooldown_minutes)
        governor_probe = AccountDrawdownGovernor(
            enabled=execution.strategy_drawdown_enabled,
            level_1=execution.strategy_drawdown_level_1,
            scale_1=execution.strategy_drawdown_scale_1,
            level_2=execution.strategy_drawdown_level_2,
            scale_2=execution.strategy_drawdown_scale_2,
            level_3=execution.strategy_drawdown_level_3,
            scale_3=execution.strategy_drawdown_scale_3,
            reduce_only_level_3=execution.strategy_drawdown_reduce_only_level_3,
            recovery_enabled=execution.strategy_drawdown_recovery_enabled,
            recovery_flat_cooldown_minutes=execution.strategy_drawdown_recovery_flat_cooldown_minutes,
            recovery_max_signal=execution.strategy_drawdown_recovery_max_signal,
        )
        governor_probe.apply_signal(0.0, 0.0, implied_drawdown, timestamp=last_fill_time)
        diagnosis["hypothetical_new_long_signal_after_recovery_cooldown"] = float(
            governor_probe.apply_signal(1.0, 0.0, implied_drawdown, timestamp=probe_time)
        )
        diagnosis["hypothetical_new_short_signal_after_recovery_cooldown"] = float(
            governor_probe.apply_signal(-1.0, 0.0, implied_drawdown, timestamp=probe_time)
        )
    return diagnosis


def _diagnosis_markdown(
    signal_activity: pd.DataFrame,
    execution_activity: pd.DataFrame,
    governor_diag: dict[str, object],
    post_last_fill: dict[str, object],
) -> str:
    signal_lines = signal_activity.to_string(index=False)
    execution_lines = execution_activity.to_string(index=False) if not execution_activity.empty else "_no execution events_"
    bullets = []
    active_years = execution_activity["year"].tolist() if not execution_activity.empty else []
    if post_last_fill.get("bars_after_last_fill", 0) > 0 and post_last_fill.get("signal_change_bars_after_last_fill", 0) > 0:
        bullets.append(
            f"- 最后一笔 fill 之后仍有 `{post_last_fill['signal_change_bars_after_last_fill']}` 次信号变化，说明信号层没有休眠。"
        )
    if governor_diag.get("freeze_risk") and governor_diag.get("recovery_enabled"):
        bullets.append(
            f"- 账户级 governor 末期仍处于 level 3 区间，但恢复机制允许在 flat `{governor_diag['recovery_flat_cooldown_minutes']}` 分钟后，以最多 `{governor_diag['recovery_max_signal']}` 的 probe 重新开仓。"
        )
    elif governor_diag.get("freeze_risk"):
        bullets.append(
            f"- 账户级 governor 相对峰值回撤约 `{governor_diag['implied_drawdown_vs_governor_peak']:.2%}`，已达到 level 3 (`{governor_diag['level_3']:.2%}`)，当前对新的多空开仓都会返回 `0.0`。"
        )
    if len(active_years) <= 1:
        bullets.append(
            f"- 诊断显示 `signal` 每年都非零，但执行层 fills/trades 只出现在 `{execution_activity['year'].min() if not execution_activity.empty else 'N/A'}`。"
        )
    else:
        bullets.append(
            f"- 恢复机制开启后，执行层已重新覆盖多年活跃度：`{active_years[0]}` 到 `{active_years[-1]}` 都有 fills/trades。"
        )
    body = "\n".join(bullets)
    return f"""# ref_plus_live 活跃度诊断

## 核心结论

{body}

## 按年份的信号活跃度

{signal_lines}

## 按年份的执行活跃度

{execution_lines}

## Governor 诊断

- `governor_peak_equity`: `{governor_diag['governor_peak_equity']:.2f}`
- `equity_last_close`: `{governor_diag['equity_last_close']:.2f}`
- `implied_drawdown_vs_governor_peak`: `{governor_diag['implied_drawdown_vs_governor_peak']:.2%}`
- `scale_at_last_equity`: `{governor_diag['scale_at_last_equity']:.2f}`
- `freeze_risk`: `{governor_diag['freeze_risk']}`
- `recovery_enabled`: `{governor_diag['recovery_enabled']}`
- `hypothetical_new_long_signal_after_recovery_cooldown`: `{governor_diag.get('hypothetical_new_long_signal_after_recovery_cooldown', 0.0):.2f}`

## 最后一笔 fill 之后

- `last_fill_time`: `{post_last_fill.get('last_fill_time')}`
- `bars_after_last_fill`: `{post_last_fill.get('bars_after_last_fill')}`
- `nonzero_signal_bars_after_last_fill`: `{post_last_fill.get('nonzero_signal_bars_after_last_fill')}`
- `signal_change_bars_after_last_fill`: `{post_last_fill.get('signal_change_bars_after_last_fill')}`
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--execution", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    params = V71LiveParams(**_read_json(args.params))
    execution = MicroBacktestConfig(**_read_json(args.execution))
    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    signaled = generate_v71_live_signals(market, params)
    result = run_micro_backtest(
        signaled.loc[signaled.index < pd.Timestamp(args.end, tz="UTC")],
        list(iter_intrabar_months(args.raw_dir, start=args.start, end=args.end)),
        funding,
        execution,
    )

    signal_activity = _yearly_signal_activity(signaled)
    execution_activity = _yearly_execution_activity(result)
    market_state = _top_counts_by_year(signaled, "v71_market_state")
    regime = _top_counts_by_year(signaled, "regime")
    speed_reason = _top_counts_by_year(signaled, "v71_speed_reason")
    live_reason = _top_counts_by_year(signaled, "v71_live_reason")
    post_last_fill = _post_last_fill_signal_activity(signaled, result)
    last_fill_ts = None if result.fills.empty else pd.to_datetime(result.fills["timestamp"], utc=True).max()
    governor_diag = _governor_freeze_diagnosis(result, execution, last_fill_ts)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    signal_activity.to_csv(output / "yearly_signal_activity.csv", index=False)
    execution_activity.to_csv(output / "yearly_execution_activity.csv", index=False)
    market_state.to_csv(output / "market_state_top_counts_by_year.csv", index=False)
    regime.to_csv(output / "regime_top_counts_by_year.csv", index=False)
    speed_reason.to_csv(output / "speed_reason_top_counts_by_year.csv", index=False)
    live_reason.to_csv(output / "live_reason_top_counts_by_year.csv", index=False)
    result.fills.to_csv(output / "micro_fills.csv", index=False)
    result.trades.to_csv(output / "micro_trades.csv", index=False)
    result.equity.to_csv(output / "micro_equity.csv", header=True)

    report = {
        "params_file": str(args.params),
        "execution_file": str(args.execution),
        "metrics": result.metrics,
        "signal_activity": signal_activity.to_dict(orient="records"),
        "execution_activity": execution_activity.to_dict(orient="records"),
        "post_last_fill": post_last_fill,
        "governor_diagnosis": governor_diag,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "diagnosis.md").write_text(
        _diagnosis_markdown(signal_activity, execution_activity, governor_diag, post_last_fill) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "freeze_risk": governor_diag["freeze_risk"],
        "post_last_fill_signal_changes": post_last_fill.get("signal_change_bars_after_last_fill", 0),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

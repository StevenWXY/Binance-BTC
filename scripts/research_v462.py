"""Small, audited V4.6.2 screen; lock selection before 2026 diagnostics."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v441_r2 import features  # noqa: E402
from btc_regime.v453 import V453Params  # noqa: E402
from btc_regime.v461 import V461Params  # noqa: E402
from btc_regime.v462 import V462Params, generate_v462_signals  # noqa: E402
import run_bitget_three_latest as latest  # noqa: E402

OUTPUT = ROOT / 'reports' / 'v4_6_2'
DATA = ROOT / 'data' / 'bitget_20261011'
START = pd.Timestamp('2020-01-01', tz='UTC')
SPLIT = pd.Timestamp('2024-01-01', tz='UTC')
LOCK_END = pd.Timestamp('2026-01-01', tz='UTC')


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def dump(path, payload):
    path.write_text(json.dumps(clean(payload), indent=2, ensure_ascii=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_params():
    payload = json.loads((ROOT / 'configs' / 'v4_6_1_params.json').read_text())
    risk = V461Params(base=V453Params(**payload['base_signal_params']), **payload['risk_overlay'])
    return V462Params(risk=risk)


def execution(maker=True):
    return MicroBacktestConfig(
        initial_cash=10_000, taker_fee_bps=6 * (1 - .60), maker_fee_bps=2 * (1 - .60),
        maker_enabled=maker, maker_resting_mode=True, maker_offset_bps=1.,
        maker_min_rest_bars=1, maker_fill_penetration_bps=1.,
        maker_fill_capacity_fraction=.25, maker_order_timeout_minutes=15,
        maker_timeout_taker=True, maker_exit_enabled=False,
        conservative_protection=True, signal_interval_minutes=60,
        equity_interval_minutes=5, execution_bar_minutes=5, periods_per_year=105120,
        base_slippage_bps=1., impact_bps=8., max_minute_participation=.02,
    )


def candidates():
    control = base_params()
    risk85 = replace(control, risk=replace(control.risk, exposure_scale=.85))
    return {
        'control_taker': (control, execution(False), 0),
        'control_maker': (control, execution(), 1),
        'risk85_maker': (risk85, execution(), 2),
        'break4_risk85': (replace(risk85, long=replace(risk85.long, breakout_hours=4)), execution(), 3),
        'cooldown1_risk85': (replace(risk85, long=replace(risk85.long, cooldown_hours=1)), execution(), 3),
        'hold48_risk85': (replace(risk85, long=replace(risk85.long, hold_hours=48)), execution(), 3),
        'trail25_risk85': (replace(risk85, long=replace(risk85.long, trail_atr=2.5)), execution(), 3),
        'reclaim_risk85': (replace(risk85, long=replace(risk85.long, entry_mode='reclaim')), execution(), 3),
    }


def complete_months(equity):
    """Exact UTC boundary returns, including the first complete month."""
    boundaries = pd.date_range(equity.index[0].ceil('D'), equity.index[-1], freq='MS')
    values = {}
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        if left in equity.index and right in equity.index:
            values[left] = float(equity.loc[right] / equity.loc[left] - 1)
    return pd.Series(values, dtype=float, name='return')


def negative_streak(values):
    longest = current = 0
    for x in values:
        current = current + 1 if x < 0 else 0
        longest = max(longest, current)
    return longest


def metrics(result, start=None, end=None):
    start = result.equity.index[0] if start is None else start
    end = result.equity.index[-1] if end is None else end
    e = result.equity.loc[start:end]
    if len(e) < 2 or start not in e.index or end not in e.index:
        raise ValueError(f'Missing exact equity boundary {start} / {end}')
    years = (end - start).total_seconds() / (365.25 * 86400)
    daily = e.loc[(e.index.hour == 0) & (e.index.minute == 0)]
    daily_returns = daily.pct_change().dropna()
    std = daily_returns.std(ddof=1)
    month = complete_months(e)
    month_std = month.std(ddof=1)
    fills, trades = result.fills, result.trades
    if not fills.empty:
        ts = pd.to_datetime(fills.timestamp, utc=True)
        fills = fills.loc[(ts >= start) & (ts < end)]
    if not trades.empty:
        ts = pd.to_datetime(trades.exit_time, utc=True)
        trades = trades.loc[(ts >= start) & (ts < end)]
    notional = float(fills.notional.sum()) if not fills.empty else 0.
    maker_notional = float(fills.loc[fills.liquidity.eq('maker'), 'notional'].sum()) if not fills.empty else 0.
    fees = float(fills.fee.sum()) if not fills.empty else 0.
    holding = (pd.to_datetime(trades.exit_time, utc=True) - pd.to_datetime(trades.entry_time, utc=True)).dt.total_seconds() / 3600 if not trades.empty else pd.Series(dtype=float)
    return {
        'total_return': e.iloc[-1] / e.iloc[0] - 1,
        'cagr': (e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1,
        'daily_sharpe': daily_returns.mean() / std * np.sqrt(365.25) if std > 0 else np.nan,
        'daily_volatility': std * np.sqrt(365.25),
        'max_drawdown': (e / e.cummax() - 1).min(),
        'monthly_mean': month.mean(), 'monthly_std': month_std,
        'monthly_sharpe': month.mean() / month_std * np.sqrt(12) if month_std > 0 else np.nan,
        'positive_month_fraction': (month > 0).mean(), 'worst_month': month.min(),
        'best_month': month.max(), 'complete_months': len(month),
        'positive_months': int((month > 0).sum()), 'losing_months': int((month < 0).sum()),
        'max_negative_streak': negative_streak(month),
        'cycles': len(trades), 'cycles_per_year': len(trades) / years,
        'long_cycles': int(trades.side.eq('long').sum()) if not trades.empty else 0,
        'short_cycles': int(trades.side.eq('short').sum()) if not trades.empty else 0,
        'median_holding_hours': holding.median(),
        'fills': len(fills), 'fees_paid': fees, 'traded_notional': notional,
        'effective_fee_bps': fees / notional * 10000 if notional else 0,
        'maker_notional_fraction': maker_notional / notional if notional else 0,
        'ending_equity': float(e.iloc[-1]),
    }


def load_data():
    cached = pd.read_pickle(DATA / 'candles_5m.pkl')
    end = pd.to_datetime(cached.index.max(), utc=True) + pd.Timedelta(minutes=5)
    latest.START, latest.END = START, end
    raw, hourly, _, funding = latest.load_data(DATA)
    return raw, hourly, funding, end


def prepared_batches(raw):
    return list(latest.batches(raw))


def replay(name, params, config, hourly, prepared, batches, funding, folder, latency=0):
    folder.mkdir(parents=True, exist_ok=True)
    before = time.monotonic()
    signal = generate_v462_signals(hourly, params, prepared=prepared)
    if latency:
        signal.index = signal.index + pd.Timedelta(hours=latency)
    result = run_micro_backtest(signal, batches, funding, config)
    with (folder / f'{name}.pkl').open('wb') as stream:
        pickle.dump(result, stream)
    out = metrics(result)
    dump(folder / f'{name}.json', {'params': asdict(params), 'execution': asdict(config), 'metrics': out, 'engine_metrics': result.metrics})
    print(f'{name}: CAGR={out["cagr"]:.2%} DD={out["max_drawdown"]:.2%} Sharpe={out["daily_sharpe"]:.3f} positive={out["positive_month_fraction"]:.2%} cycles={out["cycles"]} maker={out["maker_notional_fraction"]:.1%} ({time.monotonic()-before:.1f}s)', flush=True)
    return result


def read_result(folder, name):
    with (folder / f'{name}.pkl').open('rb') as stream:
        return pickle.load(stream)


def screen():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT / 'selection_lock.json').exists():
        raise FileExistsError('Selection already locked; use diagnostic/report, or a new versioned experiment directory.')
    raw, hourly, funding, end = load_data()
    specs = candidates()
    manifest = {
        'data_start': START, 'data_end': end, 'development_end': LOCK_END,
        'data_sha256': digest(DATA / 'candles_5m.pkl'), 'funding_sha256': digest(DATA / 'funding.pkl'),
        'funding_first_observed': funding.index.min(), 'protocol_sha256': digest(OUTPUT / 'PROTOCOL.md'),
        'code_sha256': {p: digest(ROOT / p) for p in ['src/btc_regime/micro_backtest.py', 'src/btc_regime/v462.py', 'scripts/research_v462.py']},
        'candidates': {name: {'params': asdict(p), 'execution': asdict(c), 'complexity': complexity} for name, (p, c, complexity) in specs.items()},
        'historical_data_previously_visible': True,
        'drawdown_sampling': '5-minute close equity; not intrabar account drawdown',
        'sharpe_sampling': 'UTC midnight daily returns, annualized sqrt(365.25), zero risk-free rate',
        'monthly_sampling': 'exact UTC month boundaries; includes January 2020, excludes partial October 2026',
        'funding_missing_policy': 'zero in base; stressed separately, not asserted free',
        'maintenance_model': 'inherited Binance bracket assumptions, not verified historical Bitget margin tiers',
    }
    dump(OUTPUT / 'manifest.json', manifest)
    dev_hourly = hourly.loc[hourly.index < LOCK_END]
    prepared = features(dev_hourly)
    dev_batches = prepared_batches(raw.loc[raw.index < LOCK_END])
    rows = []
    for name, (p, config, complexity) in specs.items():
        result = replay(name, p, config, dev_hourly, prepared, dev_batches, funding.loc[funding.index < LOCK_END], OUTPUT / 'development')
        row = {'candidate': name, 'complexity': complexity}
        for key, left, right in [('train', START, SPLIT), ('validation', SPLIT, LOCK_END), ('development', START, LOCK_END)]:
            row.update({f'{key}_{k}': v for k, v in metrics(result, left, right).items()})
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUTPUT / 'candidate_screen_partial.csv', index=False)
    baseline = rows[0]
    for row in rows:
        checks = {
            'both_folds_profitable': row['train_total_return'] > 0 and row['validation_total_return'] > 0,
            'sharpe_at_least_control': row['development_daily_sharpe'] >= baseline['development_daily_sharpe'],
            'month_win_at_least_control': row['development_positive_month_fraction'] >= baseline['development_positive_month_fraction'],
            'cagr_at_least_50pct': row['development_cagr'] >= .5,
            'drawdown_within_22pct': row['development_max_drawdown'] >= -.22,
            'frequency_not_lower': row['development_cycles_per_year'] >= baseline['development_cycles_per_year'],
            'frequency_within_1_6x': row['development_cycles_per_year'] <= 1.6 * baseline['development_cycles_per_year'],
        }
        row.update(checks)
        row['eligible'] = all(checks.values()) and row['candidate'] != 'control_taker'
        row['failed_guards'] = '|'.join(k for k, passed in checks.items() if not passed)
        a, b = row['train_daily_sharpe'], row['validation_daily_sharpe']
        row['score'] = (a + b) / 2 - .25 * abs(a - b) + .5 * row['development_positive_month_fraction']
    eligible = [r for r in rows if r['eligible']]
    pool = eligible or [r for r in rows if r['candidate'] != 'control_taker']
    top = max(r['score'] for r in pool)
    tied = [r for r in pool if r['score'] >= top - .03]
    chosen = sorted(tied, key=lambda r: (r['complexity'], -r['score'], r['candidate']))[0]
    lock = {'candidate': chosen['candidate'], 'passes_development_guards': bool(eligible),
            'selection_status': 'development_eligible_pending_stress' if eligible else 'diagnostic_only_no_candidate_passed',
            'selection_end': LOCK_END, 'diagnostics_used_for_selection': False,
            'failed_guards': chosen['failed_guards'], 'candidate_count': len(rows), 'chosen_row': chosen,
            'manifest_sha256': digest(OUTPUT / 'manifest.json')}
    pd.DataFrame(rows).to_csv(OUTPUT / 'candidate_screen.csv', index=False)
    dump(OUTPUT / 'selection_lock.json', lock)
    print('LOCKED ' + json.dumps(clean(lock), ensure_ascii=False), flush=True)


def funding_stress(result, raw, first_observed, adverse_bps=1.):
    """Position-path carry overlay; no re-sizing feedback, clearly a sensitivity."""
    events = pd.date_range(result.equity.index[0], min(first_observed, result.equity.index[-1]), freq='8h', inclusive='left')
    fills = result.fills.copy()
    fills.index = pd.to_datetime(fills.timestamp, utc=True)
    position = fills.groupby(level=0).position_after.last().sort_index()
    # Funding precedes same-time fills. merge_asof excludes an exact-time fill.
    frame = pd.merge_asof(pd.DataFrame({'timestamp': events}),
                          position.rename('position').reset_index().rename(columns={'index': 'timestamp'}),
                          on='timestamp', direction='backward', allow_exact_matches=False)
    pos = pd.Series(frame.position.fillna(0.).to_numpy(), index=events)
    prices = raw.trade_open.reindex(events)
    charges = pos.abs() * prices * adverse_bps / 10000
    # Five-minute boundary equity exists at each charge event before new fills.
    fractions = (charges / result.equity.reindex(events)).fillna(0.)
    factors = (1 - fractions).cumprod()
    adjusted = result.equity * factors.reindex(result.equity.index).ffill().fillna(1.)
    stressed = replace(result, equity=adjusted, returns=adjusted.pct_change().fillna(0.))
    return stressed, pd.DataFrame({'position_before_event': pos, 'price': prices, 'synthetic_charge': charges, 'equity_fraction': fractions})


def diagnostic():
    lock = json.loads((OUTPUT / 'selection_lock.json').read_text())
    name = lock['candidate']
    p, config, _ = candidates()[name]
    raw, hourly, funding, end = load_data()
    prepared = features(hourly)
    full_batches = prepared_batches(raw)
    folder = OUTPUT / 'full'
    for label, param, cfg in [('control_taker', base_params(), execution(False)), (name, p, config)]:
        replay(label, param, cfg, hourly, prepared, full_batches, funding, folder)
    selected = read_result(folder, name)
    stresses = {
        'all_taker': (replace(config, maker_enabled=False), 0),
        'maker_strict': (replace(config, maker_fill_penetration_bps=3., maker_fill_capacity_fraction=.10), 0),
        'no_rebate': (replace(config, taker_fee_bps=6., maker_fee_bps=2.), 0),
        'double_slippage': (replace(config, base_slippage_bps=2., impact_bps=16.), 0),
        'extra_hour_latency': (config, 1),
    }
    stress_rows = [{'scenario': 'base', **metrics(selected)}]
    for label, (cfg, delay) in stresses.items():
        result = replay(label, p, cfg, hourly, prepared, full_batches, funding, OUTPUT / 'stress', latency=delay)
        stress_rows.append({'scenario': label, **metrics(result)})
        pd.DataFrame(stress_rows).to_csv(OUTPUT / 'execution_stress.csv', index=False)
    adverse, carry = funding_stress(selected, raw, funding.index.min())
    carry.to_csv(OUTPUT / 'synthetic_missing_funding_charges.csv')
    adverse.equity.to_csv(OUTPUT / 'synthetic_missing_funding_equity.csv')
    stress_rows.append({'scenario': 'synthetic_adverse_1bp_per_8h_path_sensitivity', **metrics(adverse)})
    pd.DataFrame(stress_rows).to_csv(OUTPUT / 'execution_stress.csv', index=False)
    neighbors = {
        'exposure_minus005': replace(p, risk=replace(p.risk, exposure_scale=p.risk.exposure_scale-.05)),
        'exposure_plus005': replace(p, risk=replace(p.risk, exposure_scale=p.risk.exposure_scale+.05)),
    }
    if name.startswith('break4'):
        neighbors.update({f'breakout{x}': replace(p, long=replace(p.long, breakout_hours=x)) for x in (3, 5)})
    elif name.startswith('cooldown1'):
        neighbors.update({f'cooldown{x}': replace(p, long=replace(p.long, cooldown_hours=x)) for x in (0, 2)})
    elif name.startswith('hold48'):
        neighbors.update({f'hold{x}': replace(p, long=replace(p.long, hold_hours=x)) for x in (36, 60)})
    elif name.startswith('trail25'):
        neighbors.update({f'trail{x}': replace(p, long=replace(p.long, trail_atr=x)) for x in (2.25, 2.75)})
    rows = []
    for label, neighbor in neighbors.items():
        result = replay(label, neighbor, config, hourly, prepared, full_batches, funding, OUTPUT / 'neighbors')
        rows.append({'neighbor': label, **metrics(result)})
        pd.DataFrame(rows).to_csv(OUTPUT / 'parameter_neighbors.csv', index=False)
    if not any(name.startswith(prefix) for prefix in ('break4', 'cooldown1', 'hold48', 'trail25')):
        for offset in (.5, 2.):
            label = f'quote_offset_{offset}bp'
            result = replay(label, p, replace(config, maker_offset_bps=offset), hourly, prepared, full_batches, funding, OUTPUT / 'neighbors')
            rows.append({'neighbor': label, **metrics(result)})
        pd.DataFrame(rows).to_csv(OUTPUT / 'parameter_neighbors.csv', index=False)
    report()


def report():
    lock = json.loads((OUTPUT / 'selection_lock.json').read_text())
    name = lock['candidate']
    p, config, _ = candidates()[name]
    selected = read_result(OUTPUT / 'full', name)
    baseline = read_result(OUTPUT / 'full', 'control_taker')
    comparison = []
    for label, result in [('V4.6.1', baseline), ('V4.6.2_candidate', selected)]:
        end = result.equity.index[-1]
        for period, left, right in [('full', START, end), ('2020_2023', START, SPLIT), ('2024_2025', SPLIT, LOCK_END), ('2026_diagnostic', LOCK_END, end)]:
            comparison.append({'strategy': label, 'period': period, **metrics(result, left, right)})
    pd.DataFrame(comparison).to_csv(OUTPUT / 'comparison.csv', index=False)
    monthly = pd.concat({'V4.6.1': complete_months(baseline.equity), 'V4.6.2': complete_months(selected.equity)}, axis=1)
    monthly.to_csv(OUTPUT / 'monthly_comparison.csv', index_label='month_start_utc')
    selected.equity.to_csv(OUTPUT / 'v462_equity.csv')
    selected.fills.to_csv(OUTPUT / 'v462_fills.csv', index=False)
    selected.trades.to_csv(OUTPUT / 'v462_trades.csv', index=False)
    selected.funding.to_csv(OUTPUT / 'v462_observed_funding.csv', index=False)
    annual = []
    for year in range(2020, 2027):
        left = pd.Timestamp(f'{year}-01-01', tz='UTC')
        right = min(pd.Timestamp(f'{year+1}-01-01', tz='UTC'), selected.equity.index[-1])
        for label, result in [('V4.6.1', baseline), ('V4.6.2', selected)]:
            annual.append({'strategy': label, 'year': year, **metrics(result, left, right)})
    pd.DataFrame(annual).to_csv(OUTPUT / 'annual_comparison.csv', index=False)
    stress = pd.read_csv(OUTPUT / 'execution_stress.csv')
    neighbors = pd.read_csv(OUTPUT / 'parameter_neighbors.csv')
    full, control = metrics(selected), metrics(baseline)
    guards = {
        'development_passed': lock['passes_development_guards'],
        'full_cagr_at_least_50pct': full['cagr'] >= .5,
        'full_max_drawdown_within_22pct': full['max_drawdown'] >= -.22,
        'full_sharpe_at_least_baseline': full['daily_sharpe'] >= control['daily_sharpe'],
        'full_month_win_at_least_baseline': full['positive_month_fraction'] >= control['positive_month_fraction'],
        'all_taker_stress_profitable': float(stress.loc[stress.scenario.eq('all_taker'), 'cagr'].iloc[0]) > 0,
        'all_stresses_profitable': bool((stress.cagr > 0).all()),
        'all_neighbors_profitable': bool((neighbors.cagr > 0).all()),
        'zero_liquidations': selected.metrics['liquidation_count'] == 0,
    }
    status = 'research_candidate_passes_core_guards' if all(guards.values()) else 'not_accepted_research_only'
    payload = {'version': 'V4.6.2', 'based_on': 'V4.6.1', 'status': status,
               'promoted_to_default': False, 'retained_reference': 'V4.6.1',
               'candidate': name, 'parameters': asdict(p), 'execution': asdict(config),
               'fee_policy': {'gross_taker_bps': 6., 'gross_maker_bps': 2., 'rebate_fraction': .60,
                              'net_taker_bps': 2.4, 'net_maker_bps': .8, 'rebate_immediately_netted': True},
               'selection_lock': lock, 'acceptance_checks': guards,
               'limitations': ['All history previously visible; no blind holdout claim.',
                               '5m OHLC proxy; no queue position, spread, or actual post-only rejection replay.',
                               'Pre-2026-06-27 funding missing in cache; base assumes zero, separate synthetic sensitivity.',
                               'Mark prices are trade-price proxies; inherited Binance maintenance tiers unverified for Bitget.',
                               'Monthly overlay responds to BTC price, not account month-to-date drawdown.',
                               'Drawdown uses 5m closes and is not an intrabar or live guarantee.',
                               '60% rebate netted immediately; tier and settlement timing not verified.']}
    dump(ROOT / 'configs' / 'v4_6_2_params.json', payload)
    dump(OUTPUT / 'report.json', {'configuration': payload, 'comparison': comparison, 'execution_metrics': selected.metrics,
                                'stress': stress.to_dict('records'), 'neighbors': neighbors.to_dict('records')})
    print(pd.DataFrame(comparison)[['strategy','period','cagr','daily_sharpe','max_drawdown','monthly_mean','monthly_std','positive_month_fraction','cycles_per_year','maker_notional_fraction']].to_string(index=False), flush=True)
    print('FINAL STATUS ' + status, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['screen', 'diagnostic', 'report'], required=True)
    args = parser.parse_args()
    {'screen': screen, 'diagnostic': diagnostic, 'report': report}[args.stage]()


if __name__ == '__main__':
    main()

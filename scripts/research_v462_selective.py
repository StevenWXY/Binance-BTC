"""One post-screen, explicitly exploratory Maker routing experiment."""
from __future__ import annotations

from dataclasses import asdict, replace
import json

from research_v462 import (
    DATA, OUTPUT, START, SPLIT, LOCK_END, base_params, clean, digest, dump, execution,
    features, load_data, metrics, prepared_batches, read_result, replay,
)

import pandas as pd


def main():
    folder = OUTPUT / 'exploratory'
    folder.mkdir(parents=True, exist_ok=True)
    config = replace(execution(), maker_new_position_enabled=False)
    p = base_params()
    dump(folder / 'manifest.json', {
        'phase': 'one_post_screen_exploratory_execution_hypothesis',
        'candidate_count': 1, 'selection_bias_warning': 'generated after seeing the original screen and 2026 diagnostic',
        'params': asdict(p), 'execution': asdict(config),
        'protocol_sha256': digest(OUTPUT / 'EXPLORATORY_ADDENDUM.md'),
        'previous_lock_sha256': digest(OUTPUT / 'selection_lock.json'),
        'funding_sha256': digest(DATA / 'funding.pkl'),
    })
    raw, hourly, funding, end = load_data()
    prepared = features(hourly)
    batches = prepared_batches(raw)
    result = replay('taker_entry_maker_add', p, config, hourly, prepared, batches, funding, folder)
    baseline = read_result(OUTPUT / 'full', 'control_taker')
    rows = []
    for label, r in [('V4.6.1', baseline), ('selective_maker', result)]:
        for period, left, right in [('full', START, end), ('train', START, SPLIT), ('validation', SPLIT, LOCK_END), ('2026_diagnostic', LOCK_END, end)]:
            rows.append({'strategy': label, 'period': period, **metrics(r, left, right)})
    pd.DataFrame(rows).to_csv(folder / 'comparison.csv', index=False)
    a, b = metrics(result), metrics(baseline)
    checks = {
        'cagr_improves': a['cagr'] > b['cagr'],
        'sharpe_improves': a['daily_sharpe'] > b['daily_sharpe'],
        'positive_month_fraction_improves': a['positive_month_fraction'] > b['positive_month_fraction'],
        'drawdown_within_22pct': a['max_drawdown'] >= -.22,
    }
    dump(folder / 'conclusion.json', {'checks': checks, 'all_pass': all(checks.values()),
                                     'status': 'exploratory_only_unvalidated', 'full': a, 'baseline': b})
    print(pd.DataFrame(rows)[['strategy','period','cagr','daily_sharpe','max_drawdown','positive_month_fraction','maker_notional_fraction','cycles']].to_string(index=False), flush=True)
    print(json.dumps(clean(checks)), flush=True)


if __name__ == '__main__':
    main()

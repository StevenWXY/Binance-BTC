"""Verify final report consistency and deterministic execution accounting."""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from research_v462 import OUTPUT, ROOT, complete_months, digest, dump, metrics, read_result


def main():
    tests = (OUTPUT / 'verification' / 'pytest.log').read_text()
    match = re.search(r'(\d+) passed', tests)
    assert match is not None and 'failed' not in tests
    config = json.loads((ROOT / 'configs' / 'v4_6_2_params.json').read_text())
    assert config['status'] == 'not_accepted_research_only'
    assert config['promoted_to_default'] is False
    screen = pd.read_csv(OUTPUT / 'candidate_screen.csv')
    assert len(screen) == 8 and not screen.eligible.any()
    lock = json.loads((OUTPUT / 'selection_lock.json').read_text())
    old_lock = json.loads((OUTPUT / 'pre_execution_fix' / 'selection_lock.json').read_text())
    assert lock['candidate'] == old_lock['candidate'] == 'control_maker'
    baseline = read_result(OUTPUT / 'full', 'control_taker')
    old_baseline = read_result(OUTPUT / 'pre_execution_fix' / 'full', 'control_taker')
    pd.testing.assert_series_equal(baseline.equity, old_baseline.equity, check_exact=True)
    pd.testing.assert_frame_equal(baseline.fills, old_baseline.fills, check_exact=True)
    candidate = read_result(OUTPUT / 'full', 'control_maker')
    regression = read_result(OUTPUT / 'verification', 'regression_maker')
    pd.testing.assert_series_equal(candidate.equity, regression.equity, check_exact=True)
    pd.testing.assert_frame_equal(candidate.fills, regression.fills, check_exact=True)
    all_results = {
        'baseline': baseline, 'candidate': candidate,
        'selective': read_result(OUTPUT / 'exploratory', 'taker_entry_maker_add'),
    }
    for name, result in all_results.items():
        assert result.equity.index.is_monotonic_increasing and result.equity.index.is_unique
        assert result.equity.notna().all() and (result.equity > 0).all()
        assert np.isfinite(result.equity.to_numpy()).all()
        monthly = complete_months(result.equity)
        assert len(monthly) == 81
        assert monthly.index.min() == pd.Timestamp('2020-01-01', tz='UTC')
        assert monthly.index.max() == pd.Timestamp('2026-09-01', tz='UTC')
        fills = result.fills
        rates = np.where(fills.liquidity.eq('maker'), .00008, .00024)
        np.testing.assert_allclose(fills.fee, fills.notional * rates, rtol=1e-12)
        assert fills.loc[fills.reason.ne('signal'), 'liquidity'].eq('taker').all()
        assert result.metrics['liquidation_count'] == 0
    comparison = pd.read_csv(OUTPUT / 'final_comparison.csv')
    for label, result in [('V4.6.1', baseline), ('V4.6.2 Maker', candidate),
                          ('Selective Maker (exploratory)', all_results['selective'])]:
        row = comparison.loc[comparison.strategy.eq(label)].iloc[0]
        expected = metrics(result)
        for field in ['cagr','daily_sharpe','max_drawdown','positive_month_fraction','effective_fee_bps','cycles']:
            assert np.isclose(row[field], expected[field])
    stress = pd.read_csv(OUTPUT / 'execution_stress.csv')
    assert len(stress) == 7
    assert len(pd.read_csv(OUTPUT / 'parameter_neighbors.csv')) == 4
    charges = pd.read_csv(OUTPUT / 'synthetic_missing_funding_charges.csv', index_col=0)
    assert (charges.synthetic_charge >= 0).all()
    assert (charges.equity_fraction < 1).all()
    tests_list = {
        'pytest_passed': int(match.group(1)),
        'baseline_equity_and_fills_exactly_unchanged': True,
        'repaired_maker_repeat_equity_and_fills_exactly_equal': True,
        'fixed_eight_candidates_retained_and_all_failed': True,
        'original_selection_unchanged': True,
        'complete_months': 81,
        'all_fee_records_match_60pct_rebate': True,
        'protective_and_final_exits_taker': True,
        'report_metrics_match_replay_objects': True,
        'zero_simulated_liquidations': True,
        'synthetic_funding_charges_nonnegative': True,
        'source_sha256': {p: digest(ROOT / p) for p in [
            'src/btc_regime/micro_backtest.py', 'src/btc_regime/v462.py',
            'scripts/research_v462.py', 'scripts/research_v462_selective.py',
            'scripts/render_v462_report.py', 'scripts/replay_v462_execution_fix.py',
            'scripts/verify_v462.py', 'tests/test_v462.py']},
        'causality': json.loads((OUTPUT / 'verification' / 'causality.json').read_text()),
    }
    dump(OUTPUT / 'verification' / 'final_checks.json', tests_list)
    print(json.dumps(tests_list, indent=2))


if __name__ == '__main__':
    main()

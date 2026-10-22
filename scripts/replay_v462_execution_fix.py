"""Audit-preserving deterministic refresh after the zero-volume timeout repair."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import research_v462 as research
import research_v462_selective as selective
import render_v462_report as render


def main():
    out = research.OUTPUT
    archive = out / 'pre_execution_fix'
    if archive.exists():
        raise FileExistsError('Repair replay already started; do not overwrite original audit.')
    archive.mkdir()
    original = json.loads((out / 'selection_lock.json').read_text())
    # Archive only the generated artifacts of this research phase.
    preserve = {'PROTOCOL.md', 'EXPLORATORY_ADDENDUM.md', 'pre_execution_fix', 'verification'}
    for path in list(out.iterdir()):
        if path.name not in preserve:
            shutil.move(str(path), str(archive / path.name))
    research.dump(out / 'EXECUTION_FIX.json', {
        'reason': 'Resting timeout at zero liquidity incorrectly discarded the Taker fallback.',
        'original_candidate': original['candidate'],
        'original_selection_passed': original['passes_development_guards'],
        'original_selection_lock_sha256': research.digest(archive / 'selection_lock.json'),
        'additional_parameter_candidates': 0,
        'policy': 'Replay the same eight candidates after a correctness repair; keep the original diagnostic candidate.',
        'first_detected_difference': '2020-12-17 04:30 UTC equity; new Maker CAGR 52.09% vs 52.04% prior replay.',
    })
    research.screen()
    updated = json.loads((out / 'selection_lock.json').read_text())
    if updated['candidate'] != original['candidate']:
        raise AssertionError('Repair changed candidate ranking; original lock must be honored, not silently reselected.')
    updated['execution_fix_replay'] = True
    updated['original_lock'] = 'pre_execution_fix/selection_lock.json'
    updated['no_new_signal_or_execution_parameters_searched'] = True
    research.dump(out / 'selection_lock.json', updated)
    research.diagnostic()
    selective.main()
    render.main()
    print('Repaired execution replay complete; original selection and failure are retained.', flush=True)


if __name__ == '__main__':
    main()

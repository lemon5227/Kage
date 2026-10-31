"""R3f code-replay families: deterministic, the reference solution passes the real checker, the stub fails,
and no family overlaps the learned, held-out or eval families."""
import inspect
import json

import pytest

from core.evolution import code_tasks
from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import FAMILIES, make_task

REFERENCES = {'rpn_eval': ([code_tasks._rpn_reference], '_rpn_reference', ('ops', 'floor_div')),
              'run_length': ([code_tasks._rle_reference], '_rle_reference', ('count_first', 'keep_ones')),
              'grid_rotate': ([code_tasks._rotate_reference], '_rotate_reference', ('clockwise',)),
              'version_sort': ([code_tasks._version_key, code_tasks._versions_reference], '_versions_reference',
                               ('descending', 'pad'))}


@pytest.mark.parametrize('family', sorted(code_tasks.CODE_REPLAY_FAMILIES))
@pytest.mark.parametrize('seed', [13000, 13001, 13002, 13017])
def test_reference_solution_passes_and_stub_fails(tmp_path, family, seed):
    spec = code_tasks.CODE_REPLAY_FAMILIES[family](seed)
    assert spec == code_tasks.CODE_REPLAY_FAMILIES[family](seed)
    task = make_task(family, seed)
    criteria = task['scoring_criteria']
    funcs, ref, keys = REFERENCES[family]
    params = ', '.join(repr(spec['params'][k]) for k in keys)
    source = '\n\n'.join(inspect.getsource(f) for f in funcs)
    source += f"\n\ndef {spec['function']}(*args):\n    return {ref}(*args, {params})\n"
    good = tmp_path / 'good' / spec['file']
    good.parent.mkdir()
    good.write_text(source)
    assert check_python_function(good, criteria) == 1.0
    stub = tmp_path / spec['file']
    stub.write_text(task['initial_files'][spec['file']])
    assert check_python_function(stub, criteria) == 0.0
    assert any('raises' in c for c in criteria['cases']) and sum('expected' in c for c in criteria['cases']) >= 5
    json.dumps(criteria)


def test_code_families_are_registered_and_separate_from_trained_and_held_out_families():
    learned = {'subset_selection', 'interval_merge', 'log_aggregation', 'csv_transform'}
    held = {'text_normalize', 'config_migrate'}
    assert set(code_tasks.CODE_REPLAY_FAMILIES) <= set(FAMILIES)
    assert not set(code_tasks.CODE_REPLAY_FAMILIES) & (learned | held)
    for path in ('eval/stream_v1/eval.json', 'eval/stream_web_v1/eval.json'):
        tasks = json.load(open(path))['tasks']
        assert not {t['family'] for t in tasks} & set(code_tasks.CODE_REPLAY_FAMILIES)

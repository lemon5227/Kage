import pytest

from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import (make_task, manifest, public_view, split_of)


REFERENCE = '''def {fn}(lines):
    key, only = {key!r}, {only!r}
    out = {{}}
    for line in lines:
        if not isinstance(line, str):
            continue
        parts = line.split(' ', 3)
        if len(parts) < 4 or not parts[2].endswith(':') or len(parts[2]) < 2:
            continue
        level, service = parts[1].upper(), parts[2][:-1]
        if only and level not in only:
            continue
        name = level if key == 'level' else service
        out[name] = out.get(name, 0) + 1
    return out
'''


def test_instances_are_deterministic_and_split_by_seed():
    assert make_task('log_aggregation', 1001) == make_task('log_aggregation', 1001)
    assert make_task('log_aggregation', 1001) != make_task('log_aggregation', 1002)
    assert split_of(1001) == 'stream' and split_of(9001) == 'eval'
    with pytest.raises(ValueError):
        split_of(99)


def test_reference_solution_passes_and_stub_fails(tmp_path):
    for seed in range(1000, 1030):
        task = make_task('log_aggregation', seed)
        crit = task['scoring_criteria']
        path = tmp_path / crit['file']
        path.write_text(task['initial_files'][crit['file']])
        assert check_python_function(path, crit) == 0.0            # stub must fail
        from core.evolution.stream_tasks import log_aggregation
        params = log_aggregation(seed)['params']
        path.write_text(REFERENCE.format(fn=crit['function'], key=params['key'], only=params['only_levels']))
        assert check_python_function(path, crit) == 1.0


def test_paraphrases_and_names_vary():
    tasks = [make_task('log_aggregation', s) for s in range(1000, 1060)]
    assert len({t['instruction'].split(' ')[0] for t in tasks}) >= 3
    assert len({t['scoring_criteria']['function'] for t in tasks}) >= 4


def test_negative_requires_read_and_no_change(tmp_path):
    task = make_task('read_preserve', 1003)
    name, text = next(iter(task['initial_files'].items()))
    (tmp_path / name).write_text(text)
    # Evaluator semantics are covered by tests/test_evolution_read_preserve.py; here only the criteria shape.
    assert set(task['scoring_criteria']) == {'type', 'file', 'sha256'} and task['negative'] is True


def test_public_view_hides_answers_and_manifest_hash_is_stable():
    task = make_task('log_aggregation', 1005)
    assert 'scoring_criteria' not in public_view(task)
    a = manifest([('log_aggregation', 1005), ('read_preserve', 1006)])
    b = manifest([('log_aggregation', 1005), ('read_preserve', 1006)])
    assert a['sha256'] == b['sha256'] and len(a['tasks']) == 2

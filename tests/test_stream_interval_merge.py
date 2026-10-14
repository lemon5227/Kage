from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import interval_merge, make_task


REFERENCE = '''def {fn}(intervals):
    rep, keys, touching = {rep!r}, {keys!r}, {touching!r}
    pairs = [(iv[0], iv[1]) if rep == 'pair' else (iv[keys[0]], iv[keys[1]]) for iv in intervals]
    if any(s > e for s, e in pairs):
        raise ValueError("start > end")
    merged = []
    for s, e in sorted(pairs):
        if merged and (s < merged[-1][1] or (touching and s == merged[-1][1])):
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged if rep == 'pair' else [{{keys[0]: s, keys[1]: e}} for s, e in merged]
'''


def test_deterministic():
    assert interval_merge(1001) == interval_merge(1001)
    assert interval_merge(1001) != interval_merge(1002)


def test_reference_passes_stub_fails(tmp_path):
    for seed in range(1000, 1030):
        task = make_task('interval_merge', seed)
        crit = task['scoring_criteria']
        path = tmp_path / crit['file']
        path.write_text(task['initial_files'][crit['file']])
        assert check_python_function(path, crit) == 0.0
        path.write_text(REFERENCE.format(fn=crit['function'], **interval_merge(seed)['params']))
        assert check_python_function(path, crit) == 1.0, seed


def test_variety():
    specs = [interval_merge(s) for s in range(1000, 1060)]
    assert len({s['instruction'].split(' ')[0] for s in specs}) >= 3
    assert len({s['function'] for s in specs}) >= 4
    assert len({s['file'] for s in specs}) >= 3
    assert {s['params']['rep'] for s in specs} == {'pair', 'dict'}
    assert {s['params']['touching'] for s in specs} == {True, False}


def test_instruction_states_touching_rule():
    for seed in range(1000, 1020):
        spec = interval_merge(seed)
        text = spec['instruction']
        assert ('should be merged' if spec['params']['touching'] else 'should not be merged') in text
        assert 'ValueError' in text and spec['file'] in text and spec['function'] in text


def test_touching_rule_matters():
    by_rule = {}
    for seed in range(1000, 1060):
        spec = interval_merge(seed)
        if spec['params']['rep'] != 'pair':
            continue
        touch = next(c for c in spec['cases'] if c.get('touching_case'))
        by_rule.setdefault(spec['params']['touching'], []).append(len(touch['expected']))
    assert set(by_rule[True]) == {1} and min(by_rule[False]) >= 2

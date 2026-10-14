from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import make_task, subset_selection


REFERENCE = '''from itertools import combinations


def {fn}(items, capacity):
    wkey, vkey = {wkey!r}, {vkey!r}
    if capacity < 0 or any(it[wkey] <= 0 for it in items):
        raise ValueError("invalid input")
    best = (-1, None)
    for r in range(len(items) + 1):
        for combo in combinations(items, r):
            if sum(it[wkey] for it in combo) <= capacity:
                value, ids = sum(it[vkey] for it in combo), sorted(it['id'] for it in combo)
                if value > best[0] or (value == best[0] and ids < best[1]):
                    best = (value, ids)
    return best[1]
'''


def test_deterministic():
    assert subset_selection(1001) == subset_selection(1001)
    assert subset_selection(1001) != subset_selection(1002)


def test_reference_passes_stub_fails(tmp_path):
    for seed in range(1000, 1030):
        task = make_task('subset_selection', seed)
        crit = task['scoring_criteria']
        path = tmp_path / crit['file']
        path.write_text(task['initial_files'][crit['file']])
        assert check_python_function(path, crit) == 0.0
        params = subset_selection(seed)['params']
        path.write_text(REFERENCE.format(fn=crit['function'], **params))
        assert check_python_function(path, crit) == 1.0, seed


def test_variety():
    specs = [subset_selection(s) for s in range(1000, 1060)]
    assert len({s['instruction'].split(' ')[0] for s in specs}) >= 3
    assert len({s['function'] for s in specs}) >= 4
    assert len({s['file'] for s in specs}) >= 3
    assert len({s['params']['wkey'] for s in specs}) == 3


def test_instruction_states_required_rules():
    for seed in range(1000, 1020):
        spec = subset_selection(seed)
        text = spec['instruction']
        for needle in (spec['file'], spec['function'], spec['params']['wkey'], spec['params']['vkey'],
                       'ValueError', 'capacity'):
            assert needle in text, (seed, needle)


def test_tie_break_case_present():
    for seed in range(1000, 1010):
        spec = subset_selection(seed)
        ties = [c for c in spec['cases'] if c.get('tie')]
        assert len(ties) == 1
        items, capacity = ties[0]['args']
        assert len(items) == 2 and capacity == items[0][spec['params']['wkey']]
        assert ties[0]['expected'] == [min(it['id'] for it in items)]


def test_inputs_not_shared():
    spec = subset_selection(1005)
    seen = set()
    for case in spec['cases']:
        for item in case['args'][0]:
            assert id(item) not in seen
            seen.add(id(item))

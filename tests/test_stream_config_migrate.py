import copy

from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import config_migrate, make_task


REFERENCE = '''def {fn}(cfg):
    renames, grouped, section = {renames!r}, {grouped!r}, {section!r}
    if cfg.get('version') != 1:
        raise ValueError("unsupported version")
    out, group = {{'version': 2}}, {{}}
    for key, value in cfg.items():
        if key == 'version' or value is None:
            continue
        if key == 'timeout_ms':
            out['timeout_s'] = value / 1000
        elif key in grouped:
            group[key] = value
        else:
            out[renames.get(key, key)] = value
    out[section] = group
    return out
'''

MUTATING = '''def {fn}(cfg):
    if cfg.get('version') != 1:
        raise ValueError("unsupported version")
    cfg['version'] = 2
    return cfg
'''


def test_deterministic():
    assert config_migrate(9001) == config_migrate(9001)
    assert config_migrate(9001) != config_migrate(9002)


def test_reference_passes_stub_fails(tmp_path):
    for seed in range(1000, 1030):
        task = make_task('config_migrate', seed)
        crit = task['scoring_criteria']
        path = tmp_path / crit['file']
        path.write_text(task['initial_files'][crit['file']])
        assert check_python_function(path, crit) == 0.0
        path.write_text(MUTATING.format(fn=crit['function']))
        assert check_python_function(path, crit) == 0.0
        path.write_text(REFERENCE.format(fn=crit['function'], **config_migrate(seed)['params']))
        assert check_python_function(path, crit) == 1.0, seed


def test_variety_and_edges():
    specs = [config_migrate(s) for s in range(1000, 1060)]
    assert len({s['instruction'].split(' ')[0] for s in specs}) >= 3
    assert len({s['function'] for s in specs}) >= 4 and len({s['file'] for s in specs}) >= 3
    assert {s['params']['section'] for s in specs} == {'network', 'storage', 'limits'}
    for spec in specs[:10]:
        before = copy.deepcopy(spec['cases'])
        assert {'args': [{}], 'raises': 'ValueError'} in spec['cases']
        assert any(None in c['args'][0].values() for c in spec['cases'][:5])
        assert spec['cases'] == before

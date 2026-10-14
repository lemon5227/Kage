from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import make_task, text_normalize


REFERENCE = '''import re, unicodedata


def {fn}(text):
    sep, max_len = {sep!r}, {max_len!r}
    if not isinstance(text, str):
        raise TypeError("text must be str")
    ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', sep, ascii_text.lower()).strip(sep)
    if max_len is not None:
        slug = slug[:max_len].rstrip(sep)
    return slug
'''


def test_deterministic():
    assert text_normalize(9001) == text_normalize(9001)
    assert text_normalize(9001) != text_normalize(9002)


def test_reference_passes_stub_fails(tmp_path):
    for seed in range(1000, 1030):
        task = make_task('text_normalize', seed)
        crit = task['scoring_criteria']
        path = tmp_path / crit['file']
        path.write_text(task['initial_files'][crit['file']])
        assert check_python_function(path, crit) == 0.0
        path.write_text(REFERENCE.format(fn=crit['function'], **text_normalize(seed)['params']))
        assert check_python_function(path, crit) == 1.0, seed


def test_variety_and_edges():
    specs = [text_normalize(s) for s in range(1000, 1060)]
    assert len({s['instruction'].split(' ')[0] for s in specs}) >= 3
    assert len({s['function'] for s in specs}) >= 4 and len({s['file'] for s in specs}) >= 3
    assert {s['params']['sep'] for s in specs} == {'-', '_'}
    assert any(s['params']['max_len'] is None for s in specs) and any(s['params']['max_len'] for s in specs)
    for spec in specs:
        assert {'args': [None], 'raises': 'TypeError'} in spec['cases']
        if spec['params']['max_len']:
            edge = next(c for c in spec['cases'] if c.get('cut_on_separator'))
            assert len(edge['expected']) == spec['params']['max_len'] - 1

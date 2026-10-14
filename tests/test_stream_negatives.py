import runpy

from core.evolution.stream_tasks import inspect_question, lookalike_readonly, make_task


def test_deterministic_and_varied():
    for gen in (inspect_question, lookalike_readonly):
        assert gen(9501) == gen(9501)
        specs = [gen(s) for s in range(9500, 9560)]
        assert len({s['instruction'].split(' ')[0] for s in specs}) >= 3


def test_scored_as_read_preserve():
    for family in ('inspect_question', 'lookalike_readonly'):
        task = make_task(family, 9503)
        assert task['negative'] is True and task['split'] == 'eval'
        assert task['scoring_criteria']['type'] == 'read_preserve'
        assert 'cases' not in task['scoring_criteria']


def test_lookalike_is_a_correct_stream_family_solution(tmp_path):
    seen = set()
    for seed in range(9500, 9530):
        spec = lookalike_readonly(seed)
        seen.add(spec['params']['source_family'])
        assert 'It is already correct. Do not modify it.' in spec['instruction']
        path = tmp_path / spec['file']
        path.write_text(spec['initial_text'])
        assert callable(runpy.run_path(str(path))[spec['params']['function']])
    assert seen == {'log_aggregation', 'interval_merge', 'subset_selection'}


def test_lookalike_passes_its_own_family_check(tmp_path):
    from core.evolution.completion import check_python_function
    for seed in range(9500, 9510):
        spec = lookalike_readonly(seed)
        source = make_task(spec['params']['source_family'], seed)['scoring_criteria']
        path = tmp_path / spec['file']
        path.write_text(spec['initial_text'])
        assert check_python_function(path, source) == 1.0, seed

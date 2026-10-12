"""Baseline safety tests; model/Docker/service boundaries never execute."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.experiments import recovery_baseline as cli
from core.evolution.contracts import RunResult


@pytest.fixture
def setup(tmp_path, monkeypatch):
    suite = json.loads((cli.ROOT / 'eval/computer-use/g2-applicability-baseline-v1.json').read_text())
    suite_path = tmp_path / 'suite.json'
    suite_path.write_text(json.dumps(suite))
    (tmp_path / 'bundle').mkdir()
    (tmp_path / 'bundle' / 'recovery.py').write_text('def recover(state): return {}\n')
    record = tmp_path / 'active.json'
    record.write_text(json.dumps({'candidate': {'candidate_id': 'child', 'parent_ids': ['parent'],
        'target': 'recovery', 'bundle_path': str(tmp_path / 'bundle'), 'digest': 'frozen'}}))
    settings = {'model': {'local_runtime': {'host': '127.0.0.1', 'port': 18082,
        'model_name': 'agents-a1-4b', 'timeout_sec': 120}, 'hybrid': {'enabled': False}}}
    config = tmp_path / 'config.json'
    cfg = {'root': str(tmp_path / 'run'), 'candidate_record': str(record),
           'suite': str(suite_path), 'student_settings': settings}
    config.write_text(json.dumps(cfg))
    monkeypatch.setattr(cli, 'bundle_digest', lambda p: 'frozen')
    monkeypatch.setattr(cli, '_source_identity', lambda p: {'revision': 'committed', 'hashes': {'runner': 'sha'}})
    boundaries = []
    class Service:
        def __init__(self, port, root): self.root = root; boundaries.append('service')
        def __enter__(self):
            self.runtime = {'server_pid': 42, 'model_sha256': 'actual'}
            return self
        def __exit__(self, *args):
            cli.atomic_json(self.root / 'service-cleanup.json', {'owned_service': True, 'owned_service_stopped': True})
    monkeypatch.setattr(cli, 'LocalService', Service)
    monkeypatch.setattr(cli, 'DockerSkillRunner', lambda **kw: SimpleNamespace(image_id='docker-image'))
    monkeypatch.setattr(cli, 'ModelBroker', lambda settings: SimpleNamespace(background_provider=SimpleNamespace(model_name='agents-a1-4b')))
    monkeypatch.setattr(cli.SkillCatalog, 'from_bundle', lambda *a, **kw: SimpleNamespace(digests={'old': 'unchanged'}))
    monkeypatch.setattr(cli.RecoveryPolicy, 'from_bundle', lambda *a, **kw: object())
    monkeypatch.setattr(cli, 'RecordedLocalProvider', lambda *a, **kw: SimpleNamespace(kwargs=kw))
    monkeypatch.setattr(cli, 'KageChainProvider', lambda model, **kw: SimpleNamespace(model=model, kwargs=kw))
    results = []
    def evaluate(self, candidate, task):
        boundaries.append(task['task_id'])
        state = json.loads((self.root / 'baseline-state.json').read_text())
        assert state['attempts'][task['task_id']]['status'] == 'reserved'
        frozen = json.loads((self.root / 'freeze.json').read_text())
        assert frozen['runtime']['model_sha256'] == 'actual'
        provider = self.provider_factory(candidate)
        assert provider.kwargs['max_model_calls'] == 6
        assert provider.kwargs['max_tool_actions'] == 12
        assert provider.kwargs['agentic_loop_cls'].MAX_STEPS == 5
        assert self.step_isolation == 'fork' and self.kernel_max_steps == 1 and self.timeout_s == 150
        assert self.budget.config.max_api_calls == 12
        assert self.budget.config.max_output_tokens_total == 24000
        trace = self.root / (task['task_id'] + '.jsonl')
        trace.write_text(json.dumps({'action': {'name': 'skill_call', 'arguments': {'skill_id': 'old', 'digest': 'unchanged'}},
                                     'observation': {'actor': 'recovery_policy', 'success': True}}) + '\n')
        return results.pop(0) if results else RunResult(task['task_id'], 'failed' if task['family'] == 'read_preserve' else 'passed',
                        0 if task['family'] == 'read_preserve' else 1, str(trace))
    monkeypatch.setattr(cli.Promoter, 'evaluate', evaluate)
    return config, cfg, suite, suite_path, boundaries, results


def test_frozen_local_baseline_and_reentry(setup, monkeypatch):
    config, cfg, suite, path, boundaries, results = setup
    report = cli.run_baseline(config)
    assert report['can_learn'] is True
    assert report['teacher_calls'] == 0 and report['candidates_created'] == 0
    assert report['runs'][0]['skill_calls'][0]['actor'] == 'recovery_policy'
    assert report['service_cleanup']['owned_service_stopped']
    assert report['budget']['total_api_calls'] == 0  # mocked provider, no requests
    count = len(boundaries)
    monkeypatch.setattr(cli, 'DockerSkillRunner', lambda **kw: pytest.fail('repeat touched Docker'))
    assert cli.run_baseline(config) == report
    assert len(boundaries) == count
    cfg['student_settings']['model']['local_runtime']['timeout_sec'] = 100
    config.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match='protocol'):
        cli.run_baseline(config)


@pytest.mark.parametrize('change', ['cloud', 'host', 'port', 'alias', 'teacher', 'too_many', 'duplicate', 'split', 'protocol'])
def test_invalid_configuration_has_no_environment_calls(setup, change):
    config, cfg, suite, path, boundaries, results = setup
    if change == 'cloud': cfg['student_settings']['model']['broker'] = {'background': 'cloud'}
    elif change in {'host', 'port', 'alias'}:
        key, value = {'host': ('host', 'example.com'), 'port': ('port', 8080), 'alias': ('model_name', 'other')}[change]
        cfg['student_settings']['model']['local_runtime'][key] = value
    elif change == 'teacher': cfg['teacher_settings'] = '/private/must-not-be-read'
    elif change == 'too_many': suite['tasks'].append({**suite['tasks'][0], 'task_id': 'extra'})
    elif change == 'duplicate': suite['tasks'][1]['task_id'] = suite['tasks'][0]['task_id']
    elif change == 'split': suite['tasks'][0]['split'] = 'validation'
    elif change == 'protocol': suite['protocol']['teacher_calls'] = 1
    config.write_text(json.dumps(cfg)); path.write_text(json.dumps(suite))
    with pytest.raises(ValueError): cli.run_baseline(config)
    assert boundaries == []


def test_interrupted_attempt_never_replays(setup, monkeypatch):
    config, cfg, suite, path, boundaries, results = setup
    def interrupt(self, candidate, task): raise KeyboardInterrupt()
    monkeypatch.setattr(cli.Promoter, 'evaluate', interrupt)
    with pytest.raises(KeyboardInterrupt): cli.run_baseline(config)
    count = len(boundaries)
    with pytest.raises(RuntimeError, match='unresolved|interrupted'): cli.run_baseline(config)
    assert len(boundaries) == count


@pytest.mark.parametrize('reason', ['call_limit', 'step_limit', 'timeout', 'budget_exhausted'])
def test_resource_failure_does_not_authorize_learning(setup, reason):
    config, cfg, suite, path, boundaries, results = setup
    results.append(RunResult('source', 'failed', 0, '', metadata={'chain': [{'stop_reason': reason}]}))
    report = cli.run_baseline(config)
    assert not report['can_learn']
    assert len(report['runs']) == 1


def test_no_skill_call_is_not_a_learning_gap(setup):
    config, cfg, suite, path, boundaries, results = setup
    empty = config.parent / 'empty.jsonl'; empty.write_text('')
    results.append(RunResult('source', 'failed', 0, str(empty)))
    assert not cli.run_baseline(config)['can_learn']


def test_cli_config_only(setup, capsys):
    config, *_ = setup
    assert cli.main(['--config', str(config)])['can_learn']
    assert json.loads(capsys.readouterr().out)['can_learn']
    with pytest.raises(SystemExit): cli.main(['--config', str(config), '--allow-paid-teacher'])


def test_entry_exists_before_wiring(tmp_path):
    with pytest.raises(ValueError):
        cli.run_baseline(tmp_path / 'missing.json')


def test_teacher_and_mutator_paths_are_never_used(setup, monkeypatch):
    config, cfg, *_ = setup
    from core.evolution.recovery_mutator import RecoveryMutator
    monkeypatch.setattr(RecoveryMutator, '__init__', lambda *a, **k: pytest.fail('teacher mutator created'))
    read = Path.read_text
    def public_only(self, *a, **kw):
        assert '/teachers/' not in str(self) and 'deepseek-settings' not in str(self)
        return read(self, *a, **kw)
    monkeypatch.setattr(Path, 'read_text', public_only)
    report = cli.run_baseline(config)
    assert not (Path(cfg['root']) / 'teacher-budget.sqlite').exists()
    assert report['teacher_calls'] == 0


def test_changed_suite_and_candidate_are_rejected(setup):
    config, cfg, suite, suite_path, *_ = setup
    cli.run_baseline(config)
    suite['tasks'][0]['instruction'] += ' changed'
    suite_path.write_text(json.dumps(suite))
    with pytest.raises(ValueError, match='protocol'): cli.run_baseline(config)


def test_source_preflight_requires_committed_sources(tmp_path, monkeypatch):
    suite = cli.ROOT / 'eval/computer-use/g2-applicability-baseline-v1.json'
    names = [*cli.SOURCE_FILES, str(suite.relative_to(cli.ROOT))]
    def git(argv, **kwargs):
        if argv[1] == 'ls-files': return '\n'.join(names)
        if argv[1] == 'status': return ' M core/evolution/runner.py\n'
        pytest.fail('dirty code must not continue')
    monkeypatch.setattr(cli.subprocess, 'check_output', git)
    with pytest.raises(ValueError, match='commit'): cli._source_identity(suite)
    with pytest.raises(ValueError, match='committed'): cli._source_identity(tmp_path / 'outside.json')


def test_service_failure_is_persisted_without_retry(setup, monkeypatch):
    config, cfg, suite, path, boundaries, results = setup
    class BrokenService:
        def __init__(self, *a): boundaries.append('failed_startup')
        def __enter__(self): raise RuntimeError('startup failed')
        def __exit__(self, *a): pass
    monkeypatch.setattr(cli, 'LocalService', BrokenService)
    report = cli.run_baseline(config)
    assert report['stop_reason'] == 'infrastructure' and not report['can_learn']
    assert report['runs'] == []
    assert cli.run_baseline(config) == report
    assert boundaries == ['failed_startup']


def test_old_capability_requires_actual_skill_dispatch(setup):
    config, cfg, suite, path, boundaries, results = setup
    source = config.parent / 'source.jsonl'
    source.write_text(json.dumps({'action': {'name': 'skill_call'}, 'observation': {'actor': 'student'}}))
    empty = config.parent / 'empty.jsonl'; empty.write_text('')
    results.extend([RunResult('source', 'failed', 0, str(source)), RunResult('old', 'passed', 1, str(empty))])
    assert not cli.run_baseline(config)['can_learn']


def test_recovery_runtime_fault_stops_before_old_task(setup):
    config, cfg, suite, path, boundaries, results = setup
    results.append(RunResult('source', 'failed', 0, '', metadata={'chain': [{'recovery_events': [{'error': 'bad runtime'}]}]}))
    report = cli.run_baseline(config)
    assert len(report['runs']) == 1 and not report['can_learn']
    assert report['runs'][0]['failure_kind'] == 'infrastructure'


def test_old_failed_skill_attempt_is_not_retention(setup):
    config, cfg, suite, path, boundaries, results = setup
    source = config.parent / 'source.jsonl'
    source.write_text(json.dumps({'action': {'name': 'skill_call'}, 'observation': {'actor': 'student'}}))
    failed = config.parent / 'failed.jsonl'
    failed.write_text(json.dumps({'action': {'name': 'skill_call', 'arguments': {'skill_id': 'old', 'digest': 'unchanged'}},
                                 'observation': {'success': False, 'outcome': 'error', 'actor': 'recovery_policy'}}))
    results.extend([RunResult('source', 'failed', 0, str(source)), RunResult('old', 'passed', 1, str(failed))])
    assert not cli.run_baseline(config)['can_learn']


def test_old_success_with_wrong_digest_is_not_retention(setup):
    config, cfg, suite, path, boundaries, results = setup
    source = config.parent / 'source.jsonl'
    source.write_text(json.dumps({'action': {'name': 'skill_call'}, 'observation': {'actor': 'student'}}))
    wrong = config.parent / 'wrong.jsonl'
    wrong.write_text(json.dumps({'action': {'name': 'skill_call', 'arguments': {'skill_id': 'old', 'digest': 'different'}},
                                'observation': {'success': True, 'outcome': 'ok', 'actor': 'recovery_policy'}}))
    results.extend([RunResult('source', 'failed', 0, str(source)), RunResult('old', 'passed', 1, str(wrong))])
    assert not cli.run_baseline(config)['can_learn']


def test_active_bundle_change_rejected_before_service(setup, monkeypatch):
    config, cfg, suite, path, boundaries, results = setup
    monkeypatch.setattr(cli, 'bundle_digest', lambda p: 'changed')
    with pytest.raises(ValueError, match='immutable'): cli.run_baseline(config)
    assert not boundaries


def test_single_task_is_valid_and_cannot_authorize_learning(setup):
    config, cfg, suite, path, boundaries, results = setup
    suite['tasks'] = suite['tasks'][:1]
    path.write_text(json.dumps(suite))
    report = cli.run_baseline(config)
    assert len(report['runs']) == 1 and not report['can_learn']


def test_live_worker_root_lock_prevents_second_entry(setup):
    import fcntl
    config, cfg, suite, path, boundaries, results = setup
    root = Path(cfg['root']); root.mkdir()
    with (root / 'baseline.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match='already running'): cli.run_baseline(config)
    assert not boundaries

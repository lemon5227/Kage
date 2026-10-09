import asyncio
import importlib
import json
import time
from types import SimpleNamespace

import pytest


def module():
    try:
        return importlib.import_module('scripts.experiments.native_parent_reference')
    except ModuleNotFoundError:
        pytest.fail('parent reference diagnostic is missing')


def fixture(tmp_path):
    document = tmp_path/'owned.txt'
    window, app = object(), object()
    entry = (123, 'com.apple.TextEdit', app, window)
    class Driver:
        def __init__(self):
            self._windows = {'setup-ref': entry}
            self._deadline = 0
            self.failure = None
            self.url = document.as_uri()
            self.windows = [window]
        def _load(self):
            return None, None, SimpleNamespace(CFEqual=lambda a,b:a is b)
        def _get(self, element, field, default=None):
            assert self._deadline > time.monotonic()
            if field == self.failure:
                raise RuntimeError('PRIVATE -25204')
            if element is app:
                assert field == 'AXWindows'
                return self.windows
            assert element is window
            return {'AXDocument': self.url, 'AXTitle': 'owned.txt', 'AXRole': 'AXWindow'}.get(field, default)
        def snapshot(self, ref):
            assert ref == 'setup-ref' and self._windows[ref] is entry
            return {'title': 'owned.txt', 'document_url': self.url, 'targets': [{'value': 'PRIVATE'}]}
    driver = Driver()
    environment = SimpleNamespace(adapter=SimpleNamespace(driver=driver))
    setup = {'success': True, 'observation': {'window_ref': 'setup-ref', 'title': 'owned.txt', 'document_url': document.as_uri()}}
    return document, environment, setup, entry


def test_same_setup_tuple_handle_ref_and_environment_retained(tmp_path):
    m = module()
    doc, env, setup, entry = fixture(tmp_path)
    retained = m.ParentReference(env, setup, doc)
    before = retained.sample()
    after = retained.sample()
    assert retained.environment is env and retained.entry is entry
    assert before['original_window_ref'] == after['original_window_ref'] == 'setup-ref'
    assert after['retained_tuple'] is True and after['raw_scope_matches'] is True
    assert after['original_present'] is True and after['snapshot']['success'] is True
    assert 'PRIVATE' not in json.dumps(after)


def test_per_field_error_keeps_other_fields_and_unknown_scope(tmp_path):
    m = module()
    doc, env, setup, entry = fixture(tmp_path)
    retained = m.ParentReference(env, setup, doc)
    env.adapter.driver.failure = 'AXDocument'
    result = retained.sample()
    assert result['raw_scope_matches'] is None
    assert result['fields']['AXDocument']['ax_error_code'] == -25204
    assert 'AXTitle' not in result['fields']
    assert result['fields']['AXRole']['is_window'] is True
    assert result['original_present'] is True
    assert result['snapshot']['success'] is False
    assert 'PRIVATE' not in json.dumps(result)


def test_changed_document_skips_snapshot_and_title(tmp_path):
    m = module()
    doc, env, setup, entry = fixture(tmp_path)
    retained = m.ParentReference(env, setup, doc)
    env.adapter.driver.url = 'file:///other-private.txt'
    env.adapter.driver.failure = 'AXTitle'
    result = retained.sample()
    assert result['raw_scope_matches'] is False
    assert result['snapshot']['error'] == 'ScopeUnconfirmed'
    assert 'AXTitle' not in result['fields']
    assert 'private' not in json.dumps(result)


def test_missing_setup_identity_is_not_adopted(tmp_path):
    m = module()
    doc, env, setup, entry = fixture(tmp_path)
    with pytest.raises(ValueError):
        m.ParentReference(env, {'success': True}, doc)


def test_setup_failure_preserves_both_cases_and_sanitizes(tmp_path):
    m = module()
    class Environment:
        def __init__(self, doc, output): pass
        async def setup(self): raise RuntimeError('PRIVATE')
    reports = asyncio.run(m.run_cases(tmp_path, Environment, duration=.01))
    assert [r['case'] for r in reports] == ['passive', 'blocking']
    assert all(r['error'] == 'RuntimeError' for r in reports)
    assert 'PRIVATE' not in json.dumps(reports)


def test_freeze_contains_transitive_core_and_rejects_dirty_source(tmp_path, monkeypatch):
    m = module()
    paths = m.source_paths()
    assert 'core/agentic_loop.py' in paths and 'core/computer_use/native_model.py' in paths
    monkeypatch.setattr(m.subprocess, 'check_output', lambda *a, **k: ' M scripts/experiments/native_parent_reference.py\n')
    with pytest.raises(ValueError):
        asyncio.run(m.run(tmp_path/'fresh'))
    assert not (tmp_path/'fresh'/'freeze.json').exists()


def test_observer_gate_requires_valid_baseline_before_parent_wait(tmp_path):
    m = module()
    (tmp_path/'observer-ready.json').write_text(json.dumps({'baseline': {'success': True, 'owned_count': 0, 'original_present': None}}))
    with pytest.raises(ValueError):
        m.observer_baseline(tmp_path)
    (tmp_path/'observer-ready.json').write_text(json.dumps({'baseline': {'success': True, 'owned_count': 1, 'original_present': True}, 'baseline_monotonic': 1}))
    assert m.observer_baseline(tmp_path)['baseline_monotonic'] == 1


def test_reused_observer_baseline_precedes_gate_and_times_out(tmp_path, monkeypatch):
    m = module()
    calls = []
    class Reader:
        def __init__(self, doc): pass
        def sample(self):
            calls.append('baseline')
            return {'success': True, 'owned_count': 1, 'original_present': True}
    monkeypatch.setattr(m.long, 'Reader', Reader)
    monkeypatch.setattr(m.long, 'sample_loop', lambda *a: calls.append('loop'))
    m.long.observer(tmp_path/'owned.txt', tmp_path, start_gate=tmp_path/'gate', gate_timeout=0)
    ready = json.loads((tmp_path/'observer-ready.json').read_text())
    report = json.loads((tmp_path/'observer-report.json').read_text())
    assert ready['baseline']['original_present'] is True
    assert calls == ['baseline']
    assert report['error'] == 'TimeoutError'


def test_two_fast_cases_retain_setup_reference_across_owned_observer(tmp_path, monkeypatch):
    import sys
    m = module()
    original_start = m.long.start_owned
    environments = []
    class Environment:
        def __init__(self, doc, output):
            _, env, setup, entry = fixture(output)
            # Fixture identity reflects the dedicated task9 path.
            env.adapter.driver.url = doc.as_uri()
            old_get = env.adapter.driver._get
            def get(element, key, default=None):
                if key == 'AXTitle': return doc.name
                return old_get(element, key, default)
            env.adapter.driver._get = get
            old_snapshot = env.adapter.driver.snapshot
            def snapshot(ref):
                result = old_snapshot(ref)
                result['title'] = doc.name
                return result
            env.adapter.driver.snapshot = snapshot
            self.adapter = env.adapter
            self.setup_result = {**setup, 'observation': {**setup['observation'], 'title': doc.name, 'document_url': doc.as_uri()}}
            environments.append(self)
        async def setup(self): return self.setup_result
    code = '''import pathlib,json,time,sys
p=pathlib.Path(sys.argv[1]); baseline=time.monotonic()
(p/'observer-ready.json').write_text(json.dumps({'baseline':{'success':True,'owned_count':1,'original_present':True},'baseline_monotonic':baseline}))
while not (p/'parent-wait-start.json').exists(): time.sleep(.001)
start=time.monotonic(); time.sleep(.04)
(p/'observer-report.json').write_text(json.dumps({'baseline_monotonic':baseline,'sampling_start_monotonic':start,'observer_end_monotonic':time.monotonic(),'sample_count':0,'elapsed_s':.04}))
'''
    def start(command, stdout, stderr):
        return original_start([sys.executable, '-c', code, str(stdout.parent)], stdout, stderr)
    monkeypatch.setattr(m.long, 'start_owned', start)
    reports = asyncio.run(m.run_cases(tmp_path, Environment, duration=.01))
    assert len(environments) == 2
    assert all(r['retained_through_cleanup'] and r['after']['original_present'] for r in reports)
    assert all(r['observer_covers_wait'] for r in reports)
    assert all(r['sampling_complete'] is False for r in reports)
    assert all(r['main_thread'] is True for r in reports)
    assert all(r['actual_wait_s'] >= .01 for r in reports)


@pytest.mark.parametrize('failure, windows, expected', [('AXWindows', [], None), (None, [object()], False)])
def test_membership_absence_is_distinct_from_unavailable_and_scope(tmp_path, failure, windows, expected):
    m = module()
    doc, env, setup, entry = fixture(tmp_path)
    retained = m.ParentReference(env, setup, doc)
    env.adapter.driver.failure = failure
    env.adapter.driver.windows = windows
    result = retained.sample()
    assert result['original_present'] is expected
    assert result['raw_scope_matches'] is True


def test_replaced_cached_tuple_never_adopted_or_snapshotted(tmp_path):
    m = module()
    doc, env, setup, entry = fixture(tmp_path)
    retained = m.ParentReference(env, setup, doc)
    env.adapter.driver._windows['setup-ref'] = (999, 'other', object(), object())
    result = retained.sample()
    assert retained.entry is entry
    assert result['retained_tuple'] is False
    assert result['snapshot']['success'] is False
    assert result['original_pid'] == 123

import asyncio
import json

from scripts.experiments import native_lifecycle_diagnosis as diagnosis
from core.computer_use.native_model import ScopedNativeAdapter


def test_exact_url_ownership_excludes_same_name_other_file(tmp_path):
    document = tmp_path/'owned.txt'
    scoped = ScopedNativeAdapter(None, diagnosis.BUNDLE, document.name, document_path=document)
    own = {'title': document.name, 'document_url': document.as_uri(), 'window_ref': 'owned'}
    other = {**own, 'document_url': (tmp_path/'other'/document.name).as_uri()}
    assert diagnosis.owned_windows([own, other, {**own, 'document_url': ''}], scoped) == [own]


def test_protocol_fixed_two_contexts_and_bounded_no_model():
    p = diagnosis.PROTOCOL
    assert p['contexts'] == ['main', 'run_sync']
    assert p['delays_s'] == [10, 10, 10]
    assert p['max_passive_samples'] == 21 and p['passive_interval_s'] == 2
    assert p['max_actions'] == 3 and p['retries'] == 0
    assert p['model_requests'] == p['cloud_calls'] == 0
    assert diagnosis.metrics(diagnosis.EXPECTED)['terminal_newline']
    assert diagnosis.metrics(diagnosis.EXPECTED)['newlines'] == 2


def test_freeze_records_sources_and_rejects_dirty(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnosis.platform, 'platform', lambda: 'test-platform')
    monkeypatch.setattr(diagnosis.subprocess, 'check_output', lambda argv, **kw: '' if 'status' in argv else 'abc\n')
    frozen = diagnosis.freeze(tmp_path)
    assert json.loads((tmp_path/'freeze.json').read_text()) == frozen
    assert set(frozen['source_hashes']) == set(diagnosis.SOURCES)
    monkeypatch.setattr(diagnosis.subprocess, 'check_output', lambda *a, **k: ' M diagnostic')
    import pytest
    with pytest.raises(ValueError, match='commit'):
        diagnosis.freeze(tmp_path)


def test_passive_error_retained_and_never_snapshots():
    class Driver:
        def windows(self, bundle):
            raise PermissionError('denied')
        def snapshot(self, ref):
            raise AssertionError('passive must not snapshot')
    result = diagnosis.passive_sample(Driver(), None)
    assert result == {'success': False, 'error': 'PermissionError', 'message': 'denied'}


def test_probe_fixed_stage_order_fresh_refs_and_cleanup(monkeypatch, tmp_path):
    calls = []
    class Adapter:
        current = None
    class Environment:
        def __init__(self, document, output):
            self.document = document
            self.adapter = Adapter()
        async def setup(self):
            return {'success': True}
        async def reread(self):
            return observation()
        async def cleanup(self):
            calls.append('cleanup')
            return {'success': True}
    def observation():
        return {'success': True, 'observation': {'observation_id': 'fresh', 'window_ref': 'owned', 'targets': [
            {'role': 'AXTextArea', 'target_ref': 'text', 'value': diagnosis.EXPECTED},
            {'role': 'AXMenuBarItem', 'target_ref': 'menu'},
            {'role': 'AXMenuItem', 'target_ref': 'save', 'command': 's'}]}}
    class Scoped:
        save_applied = False
        actions = 0
        def __init__(self, *a, **kw):
            self.document = kw['document_path']
        async def initial(self):
            calls.append('observe')
            return observation()
        async def act(self, obs, operation, target, value=None):
            assert obs == 'fresh'
            calls.append(target)
            self.actions += 1
            if target == 'text':
                assert value == diagnosis.EXPECTED
                self.document.write_text(value)
            if target == 'save':
                self.save_applied = True
            return observation()
    original_sleep = asyncio.sleep
    async def sleep(seconds):
        calls.append(seconds)
        await original_sleep(0)
    monkeypatch.setattr(diagnosis, 'NativeDocumentEnvironment', Environment)
    monkeypatch.setattr(diagnosis, 'ScopedNativeAdapter', Scoped)
    monkeypatch.setattr(diagnosis, 'passive_sample', lambda *a: {'success': True, 'window_count': 1})
    monkeypatch.setattr(diagnosis.asyncio, 'sleep', sleep)
    result = asyncio.run(diagnosis.probe(tmp_path/'main', 'main'))
    assert calls.count(10) == 3
    assert [v for v in calls if v in ['text', 'menu', 'save', 'cleanup']] == ['text', 'menu', 'save', 'cleanup']
    assert result['actions'] == 3 and result['saved'] and result['disk_matches']
    phases = [s['phase'] for s in result['stages'] if s['phase'] != 'passive']
    assert phases.index('fresh_before_menu') < phases.index('document_menu') < phases.index('save')
    assert sum(s['phase'] == 'passive' for s in result['stages']) <= 21


def test_first_context_missing_file_retains_report_and_second_executes(monkeypatch, tmp_path):
    calls = []
    async def broken_probe(output, context):
        output.mkdir()
        calls.append(context)
        if context == 'main':
            (output/'timeline.jsonl').write_text(json.dumps({'phase': 'invalid_snapshot', 'result': {'success': False}})+'\n')
            (output/'missing.txt').read_text()
        return {'context': context, 'status': 'unknown'}
    monkeypatch.setattr(diagnosis, '_probe', broken_probe)
    monkeypatch.setattr(diagnosis, 'freeze', lambda output: {})
    output = tmp_path/'artifacts'
    results = asyncio.run(diagnosis.run(output))
    first = json.loads((output/'main'/'report.json').read_text())
    assert first['error'] == 'FileNotFoundError' and first['status'] == 'unknown'
    assert first['stages'][0]['phase'] == 'invalid_snapshot'
    assert 'preserve' in first['cleanup']
    assert calls == ['main', 'run_sync'] and len(results) == 2
    assert (output/'summary.json').exists()

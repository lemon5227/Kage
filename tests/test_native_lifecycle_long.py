import asyncio
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


def module():
    try:
        return importlib.import_module('scripts.experiments.native_lifecycle_long')
    except ModuleNotFoundError:
        pytest.fail('long lifecycle experiment is missing')


def test_reader_timeout_and_invalid_json_are_explicit():
    m = module()
    assert m.read_child([sys.executable, '-c', 'import time; time.sleep(5)'], .05)['error'] == 'ReaderTimeout'
    assert m.read_child([sys.executable, '-c', 'print("invalid secret")'], 1)['error'] == 'ReaderJSON'


def test_replacement_is_never_adopted_as_original():
    m = module()
    original = object()
    replacement = object()
    state = m.identity_state(12, original, 12, [replacement], replacement, lambda a,b:a is b)
    assert state == {'original_present': False, 'replacement_present': True, 'pid_changed': False,
                     'main_is_original': False, 'main_is_owned': True}
    assert m.identity_state(12, original, 13, [original], original, lambda a,b:a is b)['original_present'] is False


def test_blocked_parent_does_not_stop_owned_observer(tmp_path):
    m = module()
    log = tmp_path/'ticks'
    code = 'import time,pathlib; p=pathlib.Path(__import__("sys").argv[1]); '+\
           '\nfor i in range(5):\n with p.open("a") as f:f.write(str(i)+"\\n")\n time.sleep(.04)'
    child = m.start_owned([sys.executable, '-c', code, str(log)], tmp_path/'stdout', tmp_path/'stderr')
    try:
        child.wait(timeout=3)  # Synchronously blocks this parent while child samples.
        assert child.pid != __import__('os').getpid()
        assert log.read_text().splitlines() == ['0','1','2','3','4']
    finally:
        m.stop_owned(child)
    assert child.poll() is not None


def test_cleanup_only_owned_child_is_bounded(tmp_path):
    m = module()
    child = m.start_owned([sys.executable, '-c', 'import time; time.sleep(10)'], tmp_path/'out', tmp_path/'err')
    started = time.monotonic()
    result = m.stop_owned(child, .05)
    assert child.poll() is not None
    assert time.monotonic()-started < 2
    assert result['terminated'] is True


def test_sampling_maximum_and_span_preserve_error_evidence(tmp_path):
    m = module()
    def fail():
        raise ValueError('private title and content')
    result = m.sample_loop(tmp_path/'timeline', fail, lambda seconds:time.sleep(seconds), .01, 3)
    rows = [json.loads(line) for line in (tmp_path/'timeline').read_text().splitlines()]
    assert result['sample_count'] == 3
    assert result['elapsed_s'] >= .03
    assert all(row['observation']['error'] == 'ValueError' for row in rows)
    assert 'private' not in (tmp_path/'timeline').read_text()


def test_fresh_output_rejects_overwrite(tmp_path):
    m = module()
    output = tmp_path/'new'
    m.fresh_output(output)
    (output/'evidence').write_text('keep')
    with pytest.raises(FileExistsError):
        m.fresh_output(output)
    assert (output/'evidence').read_text() == 'keep'


def test_setup_failure_continues_second_case_without_editor_cleanup(tmp_path):
    m = module()
    events = []
    class Environment:
        def __init__(self, document, output):
            events.append(document.name)
        async def setup(self):
            raise RuntimeError('sensitive data')
    results = asyncio.run(m.run_cases(tmp_path, Environment))
    assert len(events) == 2
    assert [r['case'] for r in results] == ['passive', 'blocking']
    assert all(r['error'] == 'RuntimeError' and r['post_setup_ui_writes'] == 0 for r in results)
    assert 'sensitive' not in json.dumps(results)


def test_setup_environment_disables_raw_ax_trace(tmp_path):
    m = module()
    environment = m.SetupEnvironment(tmp_path/'owned.txt', tmp_path)
    assert environment.adapter.trace_path is None
    environment.record('setup', 'observe', {'success': True, 'observation': {'secret': 'content'}})
    assert 'secret' not in (tmp_path/'setup.jsonl').read_text()


def test_reader_keeps_original_handle_and_suppresses_unowned(monkeypatch, tmp_path):
    from types import SimpleNamespace
    m = module()
    document = tmp_path/'owned.txt'
    original, replacement, foreign = object(), object(), object()
    windows = [original, foreign]
    values = {original: {'AXTitle': 'owned.txt', 'AXDocument': document.as_uri()},
              replacement: {'AXTitle': 'owned.txt', 'AXDocument': document.as_uri()},
              foreign: {'AXTitle': 'PRIVATE TITLE', 'AXDocument': 'file:///PRIVATE'}}
    app = object()
    class Driver:
        def _load(self):
            return SimpleNamespace(AXUIElementCreateApplication=lambda pid:app), SimpleNamespace(
                NSRunningApplication=SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda bundle:[SimpleNamespace(processIdentifier=lambda:123)]),
                NSWorkspace=SimpleNamespace(sharedWorkspace=lambda:SimpleNamespace(frontmostApplication=lambda:None))), SimpleNamespace(CFEqual=lambda a,b:a is b)
        def _get(self, element, key, default=None):
            if element is app:
                return windows if key == 'AXWindows' else windows[0]
            return values[element].get(key, default)
        def _id(self, element, prefix):
            return 'original-ref'
    reader = m.Reader(document)
    reader.driver = Driver()
    monkeypatch.setattr(m.os, 'kill', lambda pid, signal:None)
    first = reader.sample()
    windows[:] = [replacement, foreign]
    second = reader.sample()
    assert first['original_present'] is True
    assert second['original_present'] is False and second['replacement_present'] is True
    assert second['original_window_ref'] == 'original-ref'
    assert 'PRIVATE' not in json.dumps(second)
    fresh = reader.sample(retain=False)
    assert 'original_window_ref' not in fresh


def test_failed_initial_identity_is_not_recaptured_later(tmp_path):
    m = module()
    reader = m.Reader(tmp_path/'owned.txt')
    class FailureDriver:
        def _load(self):
            raise RuntimeError('unavailable')
    reader.driver = FailureDriver()
    with pytest.raises(RuntimeError):
        reader.sample()
    assert reader.captured is True


def test_destroyed_ax_error_preserves_numeric_code():
    from core.computer_use.native_ax import AXInvalidElementError
    m = module()
    assert m.error(AXInvalidElementError('destroyed'))['ax_error_code'] == -25202


def test_unowned_title_is_never_read(tmp_path):
    from types import SimpleNamespace
    m = module()
    document = tmp_path/'owned.txt'
    foreign = object()
    app = object()
    class Driver:
        def _load(self):
            return SimpleNamespace(AXUIElementCreateApplication=lambda pid:app), SimpleNamespace(
                NSRunningApplication=SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda bundle:[SimpleNamespace(processIdentifier=lambda:123)]),
                NSWorkspace=SimpleNamespace(sharedWorkspace=lambda:SimpleNamespace(frontmostApplication=lambda:None))), SimpleNamespace(CFEqual=lambda a,b:a is b)
        def _get(self, element, key, default=None):
            if element is app:
                return [foreign] if key == 'AXWindows' else None
            if key == 'AXTitle':
                raise AssertionError('unowned title read')
            return 'file:///foreign.txt'
    reader = m.Reader(document)
    reader.driver = Driver()
    assert reader.sample()['owned_count'] == 0


def test_unknown_original_pid_does_not_claim_relaunch_or_absence():
    m = module()
    state = m.identity_state(None, None, 123, [], None, lambda a,b:a is b)
    assert state['pid_changed'] is None
    assert state['original_present'] is None


@pytest.mark.parametrize('leader_exits', [True, False])
def test_owned_group_cleanup_survives_leader_exit(tmp_path, leader_exits):
    import os
    m = module()
    pidfile = tmp_path/'reader.pid'
    code = 'import subprocess,sys,pathlib; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]); pathlib.Path(sys.argv[1]).write_text(str(p.pid))'
    if not leader_exits:
        code += '; __import__("time").sleep(30)'
    child = m.start_owned([sys.executable, '-c', code, str(pidfile)], tmp_path/'out', tmp_path/'err')
    deadline = time.monotonic()+3
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert pidfile.exists()
    reader_pid = int(pidfile.read_text())
    if leader_exits:
        child.wait(timeout=2)
    try:
        m.stop_owned(child, .1)
        deadline = time.monotonic()+2
        stopped = False
        while time.monotonic() < deadline:
            result = subprocess.run(['ps', '-p', str(reader_pid), '-o', 'stat='], capture_output=True, text=True)
            if not result.stdout.strip() or result.stdout.strip().startswith('Z'):
                stopped = True
                break
            time.sleep(.02)
        assert stopped
        assert os.getpgrp() != child.pid
    finally:
        try:
            os.kill(reader_pid, 9)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize('count, status', [(0, 'absent'), (2, 'ambiguous')])
def test_reader_nonunique_application_identity_is_explicit(tmp_path, count, status):
    from types import SimpleNamespace
    m = module()
    reader = m.Reader(tmp_path/'owned.txt')
    class Driver:
        def _load(self):
            return object(), SimpleNamespace(
                NSRunningApplication=SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda bundle:[object()]*count),
                NSWorkspace=SimpleNamespace(sharedWorkspace=lambda:SimpleNamespace(frontmostApplication=lambda:None))), object()
    reader.driver = Driver()
    result = reader.sample()
    assert result['success'] is False
    assert result['identity_status'] == status
    assert result['original_present'] is None
    assert result['pid_changed'] is None


def test_partial_timeline_keeps_actual_count_and_incomplete_span(tmp_path):
    m = module()
    (tmp_path/'timeline.jsonl').write_text('{"sample":0,"elapsed_s":0.1}\n{"sample":1,"elapsed_s":3.7}\n{"sample":')
    result = m.partial_evidence(tmp_path, {'error': 'MissingObserverReport'})
    assert result['actual_sample_count'] == 2
    assert result['actual_last_sample_elapsed_s'] == 3.7
    assert result['partial_timeline_lines'] == 1
    assert result['sampling_complete'] is False

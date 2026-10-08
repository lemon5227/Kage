"""Frozen controlled inactive TextEdit acceptance. No inference or mutation retries.

python -m scripts.experiments.native_inactive_acceptance --output DIR
Commit sources before execution. Each helper owns only its own AppKit window/process.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

from core.computer_use.native_ax import MacOSAXDriver
from core.computer_use.native_model import NativeDocumentEnvironment, ScopedNativeAdapter, check_native_completion
from core.evolution.agent_provider import run_sync
from scripts.experiments.native_lifecycle_diagnosis import passive_sample, unique, metrics
from scripts.experiments.native_menu_repair import BoundedOwnedTraceAdapter

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = 'com.apple.TextEdit'
INITIAL = 'Kage inactive acceptance.\nStatus: pending.\n'
EXPECTED = 'Kage inactive acceptance.\nStatus: explicitly saved.\n'
PROTOCOL = {
    'version': 'native-inactive-acceptance-v2-all-fresh', 'contexts': ['main', 'run_sync'],
    'attempts_per_context': 1, 'max_editor_actions_per_context': 4,
    'max_checker_cleanup_actions_per_context': 4, 'max_native_actions_per_context': 8,
    'max_app_open_requests_per_context': 2, 'activation_dispatches_max': 1,
    'helper_readiness_deadline_s': 3, 'helper_poll_interval_s': .1,
    'fresh_frontmost_reader': 'short-lived AppKit subprocess per read',
    'fresh_frontmost_timeout_s': 0.5,
    'precondition_samples': 1, 'postcondition_samples': 1,
    'checker_observation_attempts_max': 30, 'checker_observation_deadline_s': 3,
    'deadline_semantics': 'cooperative before AX calls',
    'helper_thread_semantics': 'separate process AppKit main thread in both contexts',
    'probe_thread_semantics': 'main asyncio thread then run_sync worker thread',
    'model_requests': 0, 'cloud_calls': 0, 'mutation_retries': 0,
}
SOURCES = ['scripts/experiments/native_inactive_acceptance.py',
           'tests/test_native_inactive_acceptance.py', 'scripts/experiments/native_menu_repair.py',
           'scripts/experiments/native_lifecycle_diagnosis.py',
           'core/computer_use/native_ax.py', 'core/computer_use/native_model.py',
           'core/computer_use/browser.py', 'core/evolution/agent_provider.py']

# AppKit runs on the helper's actual main thread, never the run_sync worker.
# Activation targets this process only; no hide/quit calls target other applications.
HELPER_SOURCE = '''import json, os, sys
from pathlib import Path
import AppKit
app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
    ((80, 80), (360, 120)), AppKit.NSWindowStyleMaskTitled,
    AppKit.NSBackingStoreBuffered, False)
window.setTitle_("Kage owned inactive acceptance helper")
window.makeKeyAndOrderFront_(None)
app.activateIgnoringOtherApps_(True)
Path(sys.argv[1]).write_text(json.dumps({"pid": os.getpid(), "window_created": True}))
app.run()
'''


FRESH_FRONTMOST_SOURCE = (
    'import AppKit; front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication(); '
    'print(int(front.processIdentifier()) if front else "")'
)


def fresh_frontmost_pid(*, timeout_s=0.5):
    """Read frontmost PID in a new AppKit consumer to avoid stale local state."""
    try:
        result = subprocess.run(
            [sys.executable, '-c', FRESH_FRONTMOST_SOURCE],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return int(value) if value else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def helper_frontmost_pid(*, timeout_s=0.5):
    return fresh_frontmost_pid(timeout_s=timeout_s)


class OwnedForegroundHelper:
    def __init__(self, output):
        self.output = output
        self.process = None
        self.log = None

    @property
    def pid(self):
        return self.process.pid if self.process else None

    async def start(self):
        ready = self.output/'helper-ready.json'
        self.log = (self.output/'helper.log').open('w')
        self.process = subprocess.Popen([sys.executable, '-c', HELPER_SOURCE, str(ready)],
                                        stdout=self.log, stderr=self.log)
        deadline = time.monotonic()+PROTOCOL['helper_readiness_deadline_s']
        samples = []
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return {'success': False, 'pid': self.pid, 'returncode': self.process.returncode}
            if ready.exists():
                result = json.loads(ready.read_text())
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                frontmost = helper_frontmost_pid(timeout_s=min(
                    PROTOCOL['fresh_frontmost_timeout_s'], remaining))
                samples.append(frontmost)
                if result.get('pid') == self.pid and result.get('window_created') is True and frontmost == self.pid:
                    return {**result, 'success': True, 'foreground_samples': samples}
            await asyncio.sleep(PROTOCOL['helper_poll_interval_s'])
        return {'success': False, 'pid': self.pid, 'error': 'HelperReadinessDeadline', 'foreground_samples': samples}

    def close(self):
        result = {'owned_pid': self.pid, 'stopped': False}
        try:
            if self.process:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
                result.update(stopped=True, returncode=self.process.poll())
        finally:
            if self.log:
                self.log.close()
        return result


def sample_state(observer, scope):
    result = passive_sample(observer, scope)
    if result.get('success'):
        try:
            result['frontmost_pid'] = fresh_frontmost_pid(
                timeout_s=PROTOCOL['fresh_frontmost_timeout_s'])
            if result['frontmost_pid'] is None:
                return {**result, 'success': False, 'error': 'FreshFrontmostUnavailable'}
            owned = result['owned_windows']
            result['owned_window_ref'] = owned[0]['window_ref'] if len(owned) == 1 else None
        except Exception as exc:
            return {'success': False, 'error': type(exc).__name__}
    return result


def freeze(output):
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', *SOURCES], cwd=ROOT, text=True)
    if dirty:
        raise ValueError('commit diagnostic source and tests before actual probes')
    manifest = {'protocol': PROTOCOL, 'initial': INITIAL, 'expected': EXPECTED,
                'expected_metrics': metrics(EXPECTED), 'python': platform.python_version(),
                'platform': platform.platform(), 'helper_source_sha256': hashlib.sha256(HELPER_SOURCE.encode()).hexdigest(),
                'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'source_hashes': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}}
    (output/'freeze.json').write_text(json.dumps(manifest, indent=2))


async def probe(output, context):
    output.mkdir()
    document = (output/f'kage-inactive-{context}.txt').resolve()
    document.write_text(INITIAL)
    env = NativeDocumentEnvironment(document, output)
    env.adapter = BoundedOwnedTraceAdapter(document, output/'ax-trace.jsonl')
    scope = ScopedNativeAdapter(env.adapter, BUNDLE, document.name, document_path=document, max_actions=4)
    observer = MacOSAXDriver()
    helper = OwnedForegroundHelper(output)
    started = time.monotonic()
    stages = []
    checked = {'status': 'unknown'}
    verified = False
    cleanup = None
    helper_cleanup = None

    def record(phase, result):
        row = {'phase': phase, 'elapsed_s': time.monotonic()-started, 'result': result}
        stages.append(row)
        with (output/'timeline.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')
        return result

    def require(result):
        if result.get('success') is not True:
            raise RuntimeError('stage failed; original result retained in timeline')
        return result

    async def action(obs, operation, predicate, value=None):
        target = unique(obs, predicate)
        return require(record(operation, await scope.act(obs['observation_id'], operation, target['target_ref'], value)))['observation']

    try:
        require(record('setup', await env.setup()))
        require(record('helper_start', await helper.start()))
        obs = require(record('inactive_observation', await scope.initial()))['observation']
        before = require(record('inactive_precondition', sample_state(observer, scope)))
        if (obs.get('application_active') is not False or before.get('frontmost_pid') != helper.pid
                or before.get('main_window_owned') is not True or not before.get('owned_window_ref')
                or not before.get('app_pid')):
            raise RuntimeError('controlled inactive/main owned-window precondition unavailable; no activation or fill')
        if obs.get('activation_supported') is not True:
            raise RuntimeError('owned application activation unsupported; no fill')
        obs = await action(obs, 'activate', lambda t: t['role'] == 'AXWindow' and 'activate' in t.get('operations', []))
        after = require(record('activation_postcondition', sample_state(observer, scope)))
        verified = (obs.get('application_active') is True and after.get('frontmost_pid') == before['app_pid']
                    and after.get('app_pid') == before['app_pid'] and after.get('main_window_owned') is True
                    and after.get('owned_window_ref') == before['owned_window_ref'])
        if not verified:
            raise RuntimeError('actual frontmost/same owned-window activation unverified; no fill')
        obs = await action(obs, 'fill', lambda t: t['role'] == 'AXTextArea', EXPECTED)
        obs = await action(obs, 'press', lambda t: t['role'] == 'AXMenuBarItem')
        await action(obs, 'press', lambda t: str(t.get('command', '')).lower() == 's')
        if not scope.save_applied:
            raise RuntimeError('no verified app Save applied')
        env.adapter.actor = 'checker'
        checked = record('completion', await check_native_completion(document, EXPECTED, env.reread))
        if checked['status'] == 'passed':
            env.adapter.actor = 'cleanup'
            cleanup = record('cleanup', await env.cleanup())
    except Exception as exc:
        record('failure', {'error': type(exc).__name__, 'message': str(exc)})
        record('preserve', {'reason': 'retain uncertain owned document; no mutation retry'})
    finally:
        try:
            helper_cleanup = record('helper_cleanup', helper.close())
        except Exception as exc:
            helper_cleanup = record('helper_cleanup', {'success': False, 'owned_pid': helper.pid, 'error': type(exc).__name__, 'message': str(exc)})
    report = {'context': context, 'document': str(document), 'thread': threading.current_thread().name,
              'thread_id': threading.get_ident(), 'completion': checked, 'activation_verified': verified,
              'acceptance_passed': bool(checked['status'] == 'passed' and verified
                                        and cleanup and cleanup.get('success') is True
                                        and helper_cleanup and helper_cleanup.get('stopped') is True),
              'document_cleanup': cleanup, 'helper_cleanup': helper_cleanup,
              'actions': scope.actions, 'save_applied': scope.save_applied, 'stages': stages,
              'model_requests': 0, 'cloud_calls': 0, 'native_attempts_by_phase': env.adapter.attempts,
              'native_attempts_total': sum(env.adapter.attempts.values()),
              'app_open_requests': sum(e['operation'] in {'open', 'reopen'} for e in env.events)}
    try:
        text = document.read_text()
        report['disk'] = {'expected_matches': text == EXPECTED, **metrics(text)}
    except Exception as exc:
        report['disk'] = {'error': type(exc).__name__}
    (output/'report.json').write_text(json.dumps(report, indent=2))
    return report


async def run(output):
    if output.exists():
        raise ValueError('fresh artifact directory required; no overwrites')
    output.mkdir(parents=True)
    freeze(output)
    rows = [await probe(output/'main', 'main'), run_sync(lambda: probe(output/'run_sync', 'run_sync'))]
    (output/'summary.json').write_text(json.dumps({'protocol': PROTOCOL, 'probes': rows}, indent=2))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    rows = asyncio.run(run(parser.parse_args().output.resolve()))
    print(json.dumps({'probes': [{'context': r['context'], 'completion': r['completion'],
                                  'activation_verified': r['activation_verified'],
                                  'acceptance_passed': r['acceptance_passed']} for r in rows]}))
    raise SystemExit(0 if all(r['acceptance_passed'] for r in rows) else 1)

"""Frozen, two-context deterministic TextEdit lifecycle diagnosis; no inference.

python -m scripts.experiments.native_lifecycle_diagnosis --output DIR
Only fresh dedicated documents are opened; all edits and Save use scoped AX.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import threading
import time

from core.computer_use.native_ax import MacOSAXDriver, NativeAXAdapter
from core.computer_use.native_model import NativeDocumentEnvironment, ScopedNativeAdapter
from core.evolution.agent_provider import run_sync

BUNDLE = 'com.apple.TextEdit'
EXPECTED = 'Kage native lifecycle diagnosis.\nStatus: deterministic edit saved.\n'
INITIAL = 'Kage native lifecycle diagnosis.\nStatus: pending.\n'
PROTOCOL = {'version': 'native-lifecycle-v1', 'contexts': ['main', 'run_sync'],
            'delays_s': [10, 10, 10], 'passive_interval_s': 2,
            'max_passive_samples': 21, 'max_actions': 3,
            'model_requests': 0, 'cloud_calls': 0, 'retries': 0}
SOURCES = ['scripts/experiments/native_lifecycle_diagnosis.py',
           'tests/test_native_lifecycle_diagnosis.py', 'core/computer_use/native_ax.py',
           'core/computer_use/native_model.py', 'core/evolution/agent_provider.py']
ROOT = Path(__file__).resolve().parents[2]


def metrics(text):
    return {'sha256': hashlib.sha256(text.encode()).hexdigest(), 'characters': len(text),
            'newlines': text.count('\n'), 'terminal_newline': text.endswith('\n')}


def owned_windows(windows, scoped):
    return [w for w in windows if scoped.owns(w)]


class OwnedTraceAdapter(NativeAXAdapter):
    """Keep identification traces private to the exact owned file URL."""
    def __init__(self, document, trace_path):
        super().__init__(trace_path=trace_path)
        self.scope = ScopedNativeAdapter(self, BUNDLE, document.name, document_path=document)

    def _record(self, phase, start, **data):
        result = data.get('result', {})
        if 'windows' in result:
            data['result'] = {**result, 'window_count': len(result['windows']),
                              'windows': owned_windows(result['windows'], self.scope)}
        super()._record(phase, start, **data)


def passive_sample(driver, scoped):
    """Never snapshot unrelated windows or expose their titles/URLs."""
    try:
        windows = driver.windows(BUNDLE)
        owned = owned_windows(windows, scoped)
        ax, appkit, cf = driver._load()
        apps = appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE)
        pid = int(apps[0].processIdentifier()) if len(apps) == 1 else None
        main = driver._get(ax.AXUIElementCreateApplication(pid), 'AXMainWindow') if pid else None
        main_owned = any(main is not None and cf.CFEqual(main, driver._windows[w['window_ref']][3]) for w in owned)
        return {'success': True, 'app_pid': pid, 'window_count': len(windows),
                'owned_windows': owned, 'main_window_owned': main_owned}
    except Exception as exc:
        return {'success': False, 'error': type(exc).__name__, 'message': str(exc)}


def unique(observation, predicate):
    matches = [t for t in observation['targets'] if predicate(t)]
    if len(matches) != 1:
        raise RuntimeError(f'expected one semantic target, found {len(matches)}')
    return matches[0]


def freeze(output):
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', *SOURCES], cwd=ROOT, text=True)
    if dirty:
        raise ValueError('commit diagnostic source and tests before actual probes')
    manifest = {'protocol': PROTOCOL, 'expected': EXPECTED, 'expected_metrics': metrics(EXPECTED),
                'initial_metrics': metrics(INITIAL), 'git_revision': subprocess.check_output(
                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'source_hashes': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
                'python': platform.python_version(), 'platform': platform.platform(),
                'invocation': 'python -m scripts.experiments.native_lifecycle_diagnosis --output DIR'}
    (output/'freeze.json').write_text(json.dumps(manifest, indent=2))
    return manifest


async def _probe(output, context):
    output.mkdir()
    document = output/f'kage-lifecycle-{context}.txt'
    document.write_text(INITIAL)  # Dedicated setup only.
    environment = NativeDocumentEnvironment(document, output)
    environment.adapter = OwnedTraceAdapter(document, output/'ax-trace.jsonl')
    scoped = ScopedNativeAdapter(environment.adapter, BUNDLE, document.name,
                                 document_path=document, max_actions=3)
    observer = MacOSAXDriver()  # Independent caches; never invalidates active refs.
    started = time.monotonic()
    report = {'context': context, 'thread': threading.current_thread().name, 'thread_id': threading.get_ident(),
              'document': str(document.resolve()), 'model_requests': 0, 'cloud_calls': 0, 'stages': []}

    def record(phase, result):
        entry = {'phase': phase, 'elapsed_s': round(time.monotonic()-started, 6), 'result': result}
        report['stages'].append(entry)
        with (output/'timeline.jsonl').open('a') as stream:
            stream.write(json.dumps(entry)+'\n')
        return result

    async def safe(phase, operation):
        try:
            return record(phase, await operation())
        except Exception as exc:
            return record(phase, {'success': False, 'error': type(exc).__name__, 'message': str(exc)})

    async def passive():
        for index in range(PROTOCOL['max_passive_samples']):
            record('passive', {'sample': index, **passive_sample(observer, scoped)})
            await asyncio.sleep(PROTOCOL['passive_interval_s'])

    def audit(phase, result):
        try:
            obs = result.get('observation', {})
            areas = [t for t in obs.get('targets', []) if t['role'] == 'AXTextArea']
            record(phase, {'observation_id': obs.get('observation_id'), 'window_ref': obs.get('window_ref'),
                           'areas': [{'target_ref': t['target_ref'], **metrics(t['value']),
                                      'expected_matches': t['value'] == EXPECTED} for t in areas],
                           'disk': metrics(document.read_text()), 'disk_matches': document.read_text() == EXPECTED})
        except Exception as exc:
            record(phase, {'success': False, 'status': 'unknown', 'error': type(exc).__name__, 'message': str(exc)})

    await safe('setup', environment.setup)
    initial = await safe('initial', scoped.initial)
    task = asyncio.create_task(passive())
    try:
        await asyncio.sleep(10)
        async def fill():
            obs = initial['observation']
            area = unique(obs, lambda t: t['role'] == 'AXTextArea')
            return await scoped.act(obs['observation_id'], 'fill', area['target_ref'], EXPECTED)
        filled = await safe('fill', fill)
        audit('after_fill_audit', filled)
        await asyncio.sleep(10)
        observed = await safe('after_second_delay_observe', scoped.initial)
        audit('before_save_audit', observed)
        await asyncio.sleep(10)
        fresh = await safe('fresh_before_menu', scoped.initial)
        async def menu():
            obs = fresh['observation']
            target = unique(obs, lambda t: t['role'] == 'AXMenuBarItem')
            return await scoped.act(obs['observation_id'], 'press', target['target_ref'])
        opened = await safe('document_menu', menu)
        async def save():
            obs = opened['observation']
            target = unique(obs, lambda t: str(t.get('command', '')).lower() == 's')
            return await scoped.act(obs['observation_id'], 'press', target['target_ref'])
        saved = await safe('save', save)
        await asyncio.sleep(.3)
        audit('after_save_audit', saved)
        # One bounded fresh diagnostic observation; no rescue actions.
        await safe('final_fresh_observe', scoped.initial)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        disk_matches = document.read_text() == EXPECTED
    except Exception as exc:
        disk_matches = None
        record('disk_final_error', {'success': False, 'status': 'unknown', 'error': type(exc).__name__, 'message': str(exc)})
    if scoped.save_applied and disk_matches:
        reread = await safe('trusted_reopen', environment.reread)
        audit('reopened_audit', reread)
        await safe('cleanup', environment.cleanup)
    else:
        record('cleanup', {'success': False, 'reason': 'preserve unsaved/uncertain state; no destructive prompt response'})
    report['saved'] = scoped.save_applied
    report['disk_matches'] = disk_matches
    report['actions'] = scoped.actions
    report['elapsed_s'] = round(time.monotonic()-started, 6)
    (output/'report.json').write_text(json.dumps(report, indent=2))
    return report


async def probe(output, context):
    """Retain partial evidence on any failure; never prevent the second context."""
    try:
        return await _probe(output, context)
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        timeline = output/'timeline.jsonl'
        stages = [json.loads(line) for line in timeline.read_text().splitlines()] if timeline.exists() else []
        report = {'context': context, 'status': 'unknown', 'model_requests': 0, 'cloud_calls': 0,
                  'error': type(exc).__name__, 'message': str(exc), 'stages': stages,
                  'cleanup': 'preserve uncertain state; no rescue or destructive action'}
        (output/'report.json').write_text(json.dumps(report, indent=2))
        return report


async def run(output):
    if output.exists():
        raise ValueError('use a fresh artifact directory; no retries/overwrites')
    output.mkdir(parents=True)
    freeze(output)
    main = await probe(output/'main', 'main')
    threaded = run_sync(lambda: probe(output/'run_sync', 'run_sync'))
    (output/'summary.json').write_text(json.dumps({'protocol': PROTOCOL, 'probes': [main, threaded]}, indent=2))
    return [main, threaded]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve()))

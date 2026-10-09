"""Task9 original setup AX reference, fixed two 180-second read-only cases.

Only --output is public. Synchronous sleep is a proxy, not inference load.
No model/cloud requests or UI writes after setup. AX deadlines are cooperative.
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

from scripts.experiments import native_lifecycle_long as long

ROOT = long.ROOT
PROTOCOL = {**long.PROTOCOL, 'version': 'task9-parent-reference-v1',
            'parent_query': 'same setup environment, driver, window_ref, tuple and raw AX handle before/after wait',
            'blocking_limit': 'main-thread synchronous sleep proxy; no inference-load conclusion',
            'snapshot_scope': 'exact original document URL and title before original-driver snapshot'}


def source_paths():
    # Conservative closure: freeze every local core Python helper, including lazy
    # imports, instead of pretending a direct-import list is transitive coverage.
    paths = {str(p.relative_to(ROOT)) for p in (ROOT/'core').rglob('*.py')}
    paths.update(str(Path(p).relative_to(ROOT)) for p in long.SOURCES)
    paths.update(['scripts/__init__.py', 'scripts/experiments/__init__.py',
                  'scripts/experiments/native_parent_reference.py',
                  'scripts/experiments/native_lifecycle_long.py',
                  'tests/test_native_parent_reference.py'])
    return sorted(p for p in paths if (ROOT/p).is_file())


class ParentReference:
    """Own the setup lifetime; never enumerate via driver.windows or replace it."""
    def __init__(self, environment, setup, document):
        self.environment = environment
        self.driver = environment.adapter.driver
        self.document = document
        observation = setup.get('observation', {})
        self.ref = observation.get('window_ref')
        if (not self.ref or observation.get('title') != document.name or
                not long.same_document_url(observation.get('document_url', ''), document)):
            raise ValueError('setup identity unavailable')
        self.entry = self.driver._windows.get(self.ref)
        if self.entry is None or len(self.entry) != 4:
            raise ValueError('setup handle unavailable')
        self.pid, self.bundle, self.app, self.window = self.entry

    def sample(self):
        d = self.driver
        result = {'original_window_ref': self.ref, 'original_pid': self.pid,
                  'retained_environment': self.environment.adapter.driver is d,
                  'retained_tuple': d._windows.get(self.ref) is self.entry,
                  'raw_scope_matches': None, 'original_present': None, 'fields': {}}
        d._deadline = time.monotonic()+3  # Previous setup deadline expired during wait.
        def field(name, callback):
            try:
                value = callback()
                result['fields'][name] = {'success': True, **value}
                return value
            except Exception as exc:
                result['fields'][name] = long.error(exc)
                return None
        field('original_pid_exists', lambda: {'exists': long.pid_exists(self.pid)})
        def membership():
            windows = d._get(self.app, 'AXWindows', None)
            if windows is None:
                raise ValueError('windows unavailable')
            if len(windows) > 40:
                raise ValueError('window bound exceeded')
            cf = d._load()[2]
            return {'present': any(cf.CFEqual(self.window, candidate) for candidate in windows),
                    'window_count': len(windows)}
        present = field('AXWindows', membership)
        if present is not None:
            result['original_present'] = bool(present['present'])
        url = field('AXDocument', lambda: {'matches': long.same_document_url(str(d._get(self.window, 'AXDocument', '')), self.document)})
        title = None
        if url is not None and url['matches']:
            title = field('AXTitle', lambda: {'matches': str(d._get(self.window, 'AXTitle', '')) == self.document.name})
        field('AXRole', lambda: {'is_window': d._get(self.window, 'AXRole') == 'AXWindow'})
        if url is not None:
            result['raw_scope_matches'] = False if not url['matches'] else (title['matches'] if title else None)
        result['snapshot'] = {'success': False, 'error': 'ScopeUnconfirmed'}
        if result['raw_scope_matches'] is True and result['retained_tuple'] and result['retained_environment']:
            try:
                snapshot = d.snapshot(self.ref)
                result['snapshot'] = {'success': True,
                    'scope_matches': snapshot.get('title') == self.document.name and long.same_document_url(snapshot.get('document_url', ''), self.document),
                    'target_count': len(snapshot.get('targets', [])), 'truncated': snapshot.get('truncated')}
            except Exception as exc:
                result['snapshot'] = long.error(exc)
        return result


def observer_baseline(directory):
    ready = json.loads((directory/'observer-ready.json').read_text())
    baseline = ready.get('baseline', {})
    if not (baseline.get('success') is True and baseline.get('owned_count') == 1 and baseline.get('original_present') is True):
        raise ValueError('independent original baseline unavailable')
    return ready


async def run_cases(output, environment_factory=long.SetupEnvironment, *, duration=180):
    reports = []
    for case in PROTOCOL['cases']:
        directory = output/case
        directory.mkdir()
        document = directory/f'kage-task9-{case}.txt'
        report = {'case': case, 'post_setup_ui_writes': 0, 'model_requests': 0, 'cloud_calls': 0,
                  'parent_pid': long.os.getpid(), 'main_thread': threading.current_thread() is threading.main_thread()}
        child = None
        retained = None
        started = time.monotonic()
        try:
            document.write_text(long.INITIAL)
            environment = environment_factory(document, directory)
            setup = await environment.setup()
            if not setup.get('success'):
                raise ValueError('setup failed')
            retained = ParentReference(environment, setup, document)
            report['setup_success'] = True
            report['before'] = retained.sample()
            report['parent_baseline_verified'] = (report['before']['original_present'] is True and report['before']['raw_scope_matches'] is True and report['before']['snapshot'].get('success') is True)
            long.write_json(directory/'parent-before.json', report['before'])
            child = long.start_owned([sys.executable, '-m', 'scripts.experiments.native_parent_reference', '--observer', str(document), '--output', str(directory)],
                                     directory/'observer.stdout', directory/'observer.stderr')
            startup = time.monotonic()
            while not (directory/'observer-ready.json').exists():
                if child.poll() is not None or time.monotonic()-startup >= 15:
                    raise TimeoutError('observer startup')
                await asyncio.sleep(.05)
            report['observer_baseline'] = observer_baseline(directory)
            wait_started = time.monotonic()
            report['parent_wait_start_monotonic'] = wait_started
            long.write_json(directory/'parent-wait-start.json', {'parent_wait_start_monotonic': wait_started})
            if case == 'blocking':
                time.sleep(duration)
            else:
                await asyncio.sleep(duration)
            report['actual_wait_s'] = time.monotonic()-wait_started
            report['parent_wait_end_monotonic'] = time.monotonic()
            report['after'] = retained.sample()
            report['parent_after_end_monotonic'] = time.monotonic()
            long.write_json(directory/'parent-after.json', report['after'])
            deadline = startup+15+duration+30
            while child.poll() is None and time.monotonic() < deadline:
                await asyncio.sleep(.1)
            report['observer_deadline_exceeded'] = child.poll() is None
        except Exception as exc:
            report.update(long.error(exc))
        finally:
            if child is not None:
                try:
                    report['owned_cleanup'] = long.stop_owned(child)
                except Exception as exc:
                    report['owned_cleanup'] = long.error(exc)
                path = directory/'observer-report.json'
                try:
                    report['observer'] = json.loads(path.read_text()) if path.exists() else {'success': False, 'error': 'MissingObserverReport'}
                except (ValueError, OSError) as exc:
                    report['observer'] = long.error(exc)
                observer = report['observer']
                report['observer_covers_wait'] = (observer.get('baseline_monotonic', float('inf')) <= report.get('parent_wait_start_monotonic', -1) and observer.get('observer_end_monotonic', -1) >= report.get('parent_wait_end_monotonic', float('inf')))
                report['sampling_start_after_parent_wait_s'] = observer.get('sampling_start_monotonic', 0)-report['parent_wait_start_monotonic'] if 'sampling_start_monotonic' in observer and 'parent_wait_start_monotonic' in report else None
                report.update(long.partial_evidence(directory, report['observer']))
            report['retained_through_cleanup'] = retained is not None and retained.environment.adapter.driver is retained.driver and retained.driver._windows.get(retained.ref) is retained.entry
            report['disk'] = long.metrics(document)
            report['elapsed_s'] = time.monotonic()-started
            long.write_json(directory/'report.json', report)
            reports.append(report)
    long.write_json(output/'summary.json', {'protocol': PROTOCOL, 'cases': reports})
    return reports


async def run(output):
    long.fresh_output(output)
    paths = source_paths()
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT, text=True):
        raise ValueError('commit frozen source and tests before desktop experiment')
    long.write_json(output/'freeze.json', {'protocol': PROTOCOL, 'python': platform.python_version(),
        'platform': platform.platform(), 'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_hashes': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}})
    return await run_cases(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--observer', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.observer:
        long.observer(args.observer.resolve(), args.output.resolve(), start_gate=args.output.resolve()/'parent-wait-start.json')
        sys.exit(0)
    results = asyncio.run(run(args.output.resolve()))
    print(json.dumps({'cases': [{k: r.get(k) for k in ('case', 'error', 'observer_deadline_exceeded')} for r in results]}))

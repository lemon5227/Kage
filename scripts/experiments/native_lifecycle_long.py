"""Task8 frozen 180-second independent read-only observer experiment.

Only --output is public. Internal observer/reader modes create no UI. Blocking
sleep is a synchronous proxy; it provides no model/HTTP/CPU causal evidence.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time

from core.computer_use.native_ax import MacOSAXDriver
from core.computer_use.native_model import NativeDocumentEnvironment, same_document_url

BUNDLE = 'com.apple.TextEdit'
INITIAL = 'Kage Task8 lifecycle fixture.\nStatus: initial.\n'
ROOT = Path(__file__).resolve().parents[2]
MODULE = 'scripts.experiments.native_lifecycle_long'
PROTOCOL = {'version': 'task8-long-v1', 'cases': ['passive', 'blocking'],
            'duration_s': 180, 'interval_s': 2, 'max_samples': 90,
            'reader_timeout_s': 3, 'startup_allowance_s': 15,
            'observer_grace_s': 30, 'cleanup_wait_s': 2,
            'model_requests': 0, 'cloud_calls': 0, 'post_setup_ui_writes': 0,
            'bounds': 'cooperative AX sampling; parent wall deadline includes startup and grace'}
SOURCES = [__file__, str(ROOT/'tests/test_native_lifecycle_long.py'),
           str(ROOT/'core/computer_use/native_ax.py'), str(ROOT/'core/computer_use/native_model.py')]


def error(exc):
    # Never serialize exception messages: they may contain another title/content.
    codes = re.findall(r'-252\d{2}', str(exc))
    return {'success': False, 'error': type(exc).__name__, 'ax_error_code': int(codes[-1]) if codes else {'AXInvalidElementError': -25202, 'AXReadUnavailableError': -25204}.get(type(exc).__name__)}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2))


def metrics(document):
    try:
        data = document.read_bytes()
        return {'success': True, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'initial_matches': data == INITIAL.encode()}
    except Exception as exc:
        return error(exc)


def fresh_output(output):
    output.mkdir(parents=True, exist_ok=False)


def start_owned(command, stdout, stderr):
    with stdout.open('wb') as out, stderr.open('wb') as err:
        return subprocess.Popen(command, stdout=out, stderr=err, cwd=ROOT)


def stop_owned(child, wait=2):
    result = {'pid': child.pid, 'terminated': False, 'killed': False}
    if child.poll() is None:
        child.terminate()
        result['terminated'] = True
        try:
            child.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            child.kill()
            result['killed'] = True
            child.wait(timeout=wait)
    result['returncode'] = child.poll()
    return result


def read_child(command, timeout=3):
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=ROOT)
    try:
        try:
            stdout, _ = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'ReaderTimeout', 'pid': child.pid}
        if child.returncode:
            return {'success': False, 'error': 'ReaderExit', 'returncode': child.returncode, 'pid': child.pid}
        try:
            value = json.loads(stdout)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError):
            return {'success': False, 'error': 'ReaderJSON', 'pid': child.pid}
    finally:
        stop_owned(child)


def identity_state(original_pid, original, current_pid, owned, main, equal):
    present = current_pid == original_pid and original is not None and any(equal(original, w) for w in owned)
    return {'original_present': present,
            'replacement_present': any(current_pid != original_pid or original is None or not equal(original, w) for w in owned),
            'pid_changed': current_pid != original_pid,
            'main_is_original': present and main is not None and bool(equal(original, main)),
            'main_is_owned': main is not None and any(equal(main, w) for w in owned)}


class Reader:
    def __init__(self, document):
        self.document = document
        self.driver = MacOSAXDriver(timeout_seconds=3)
        self.original_pid = None
        self.original = None
        self.original_ref = None
        self.captured = False

    def sample(self, retain=True):
        capture = retain and not self.captured
        if capture:
            self.captured = True  # Even an initial read failure cannot adopt a later replacement.
        return self._sample(retain, capture)

    def _sample(self, retain, capture):
        d = self.driver
        ax, appkit, cf = d._load()
        d._deadline = time.monotonic()+3
        apps = appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE)
        pid = int(apps[0].processIdentifier()) if len(apps) == 1 else None
        front = appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        front_pid = int(front.processIdentifier()) if front else None
        app = ax.AXUIElementCreateApplication(pid) if pid else None
        windows = d._get(app, 'AXWindows', []) if app else []
        if len(windows) > 40:
            raise ValueError('window bound exceeded')
        owned = [w for w in windows if str(d._get(w, 'AXTitle', '')) == self.document.name
                 and same_document_url(str(d._get(w, 'AXDocument', '')), self.document)]
        if capture:
            self.original_pid = pid
            if len(owned) == 1:
                self.original = owned[0]
                self.original_ref = d._id(self.original, 'w')
        main = d._get(app, 'AXMainWindow') if app else None
        result = {'success': True, 'app_pid': pid, 'frontmost_pid': front_pid,
                  'window_count': len(windows), 'owned_count': len(owned),
                  'owned_url': self.document.resolve().as_uri() if owned else None}
        if retain:
            alive = False
            if self.original_pid:
                try:
                    os.kill(self.original_pid, 0)
                    alive = True
                except ProcessLookupError:
                    pass
                except PermissionError:
                    alive = True
            result.update(original_pid=self.original_pid, original_window_ref=self.original_ref,
                          original_pid_exists=alive,
                          **identity_state(self.original_pid, self.original, pid, owned, main, cf.CFEqual))
        return result


def sample_loop(timeline, sample, wait, interval=2, maximum=90):
    started = time.monotonic()
    count = 0
    for index in range(min(maximum, 90)):
        try:
            observation = sample()
        except Exception as exc:
            observation = error(exc)
        row = {'sample': index, 'elapsed_s': time.monotonic()-started, 'observation': observation}
        with timeline.open('a') as stream:
            stream.write(json.dumps(row)+'\n')
        count += 1
        wait(max(0, started+(index+1)*interval-time.monotonic()))
    return {'sample_count': count, 'elapsed_s': time.monotonic()-started}


def observer(document, output):
    reader = Reader(document)
    def sample():
        try:
            cached = reader.sample()
        except Exception as exc:
            cached = error(exc)
        fresh = read_child([sys.executable, '-m', MODULE, '--reader', str(document)])
        return {'cached': cached, 'fresh': fresh, 'disk': metrics(document)}
    def pump(seconds):
        import Foundation
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            Foundation.NSRunLoop.currentRunLoop().runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(min(.05, until-time.monotonic())))
    report = {'pid': os.getpid(), 'main_thread': threading.current_thread() is threading.main_thread()}
    write_json(output/'observer-ready.json', report)
    try:
        report.update(sample_loop(output/'timeline.jsonl', sample, pump))
    except Exception as exc:
        report.update(error(exc))
    finally:
        write_json(output/'observer-report.json', report)


class SetupEnvironment(NativeDocumentEnvironment):
    def __init__(self, document, output):
        super().__init__(document, output)
        self.adapter.trace_path = None

    def record(self, actor, operation, result):
        # Existing environment performs setup open+read only; suppress snapshots/content.
        safe = {'actor': actor, 'operation': operation, 'success': result.get('success'),
                'error': result.get('error')}
        with (self.output/'setup.jsonl').open('a') as stream:
            stream.write(json.dumps(safe)+'\n')
        return result


async def run_cases(output, environment_factory=SetupEnvironment):
    reports = []
    for case in PROTOCOL['cases']:
        directory = output/case
        directory.mkdir()
        document = directory/f'kage-task8-{case}.txt'
        report = {'case': case, 'post_setup_ui_writes': 0, 'model_requests': 0, 'cloud_calls': 0}
        child = None
        started = time.monotonic()
        try:
            document.write_text(INITIAL)
            setup = await environment_factory(document, directory).setup()
            if not setup.get('success'):
                raise RuntimeError('setup failed')
            report['setup_success'] = True
            child = start_owned([sys.executable, '-m', MODULE, '--observer', str(document), '--output', str(directory)],
                                directory/'observer.stdout', directory/'observer.stderr')
            startup = time.monotonic()
            while not (directory/'observer-ready.json').exists():
                if child.poll() is not None or time.monotonic()-startup >= 15:
                    raise TimeoutError('observer startup')
                await asyncio.sleep(.05)
            if case == 'blocking':
                time.sleep(180)
            else:
                await asyncio.sleep(180)
            deadline = startup+15+180+30
            while child.poll() is None and time.monotonic() < deadline:
                await asyncio.sleep(.1)
            report['observer_deadline_exceeded'] = child.poll() is None
            path = directory/'observer-report.json'
            report['observer'] = json.loads(path.read_text()) if path.exists() else {'success': False, 'error': 'MissingObserverReport'}
        except Exception as exc:
            report.update(error(exc))
        finally:
            if child is not None:
                report['owned_cleanup'] = stop_owned(child)
            report['disk'] = metrics(document)
            report['elapsed_s'] = time.monotonic()-started
            write_json(directory/'report.json', report)
            reports.append(report)
    write_json(output/'summary.json', {'protocol': PROTOCOL, 'cases': reports})
    return reports


async def run(output):
    fresh_output(output)
    paths = [str(Path(p).relative_to(ROOT)) for p in SOURCES]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT, text=True):
        raise ValueError('commit source and tests before desktop experiment')
    write_json(output/'freeze.json', {'protocol': PROTOCOL, 'python': platform.python_version(),
        'platform': platform.platform(), 'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_hashes': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}})
    return await run_cases(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--observer', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--reader', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reader:
        try:
            result = Reader(args.reader.resolve()).sample(retain=False)
        except Exception as exc:
            result = error(exc)
        print(json.dumps(result))
    elif args.observer and args.output:
        observer(args.observer.resolve(), args.output.resolve())
    elif args.output:
        results = asyncio.run(run(args.output.resolve()))
        print(json.dumps({'cases': [{k: r.get(k) for k in ('case', 'error', 'observer_deadline_exceeded')} for r in results]}))
    else:
        parser.error('--output required')

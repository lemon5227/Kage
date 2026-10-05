"""Managed serial browser experiment jobs for the controlled local task pages."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any

from core.background_lane import BackgroundLane
from core.background_worker import BackgroundWorker
from core.computer_use.task_worker import ROOT, _model_config, task_catalog


class BrowserTaskService:
    WORKER_MODULE = "task_worker"
    RUN_DEADLINE_SECONDS = 480
    STARTUP_STOP_WAIT_SECONDS = 1

    def __init__(self, run_root, config_loader, on_event=None):
        self.run_root = Path(run_root).expanduser().resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.config_loader = config_loader
        self.on_event = on_event
        self._lane = BackgroundLane()
        self._requests: dict[str, dict] = {}
        self._results: dict[str, dict] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._startups: dict[str, asyncio.Task] = {}
        self._late_startups: set[asyncio.Task] = set()
        self._late_cleanup_tasks: set[asyncio.Task] = set()
        self._deadlines: dict[str, float] = {}
        self._closed = False
        self._worker = BackgroundWorker(lane=self._lane, processor=self._process, on_event=self._event)

    def _config(self) -> dict:
        loaded = self.config_loader()
        if not isinstance(loaded, dict):
            raise ValueError('config_loader must return a dictionary')
        return loaded

    def catalog(self) -> dict:
        config = self._config()
        model = config.get('model') or {}
        local = model.get('local_runtime') or {}
        cloud = model.get('cloud_api') or {}
        local_ok = True
        try:
            _model_config(config, 'local')
        except ValueError:
            local_ok = False
        cloud_ok = True
        try:
            _model_config(config, 'cloud')
        except ValueError:
            cloud_ok = False
        tasks = [{'task_id': task['task_id'], 'title': task['fixture']['title'],
                  'instruction': task['instruction'], 'check_available': bool(task.get('scoring_criteria'))}
                 for task in task_catalog().values()]
        return {'tasks': tasks, 'executors': [
            {'id': 'local', 'model_name': local.get('model_name') or 'local-model', 'configured': local_ok},
            {'id': 'cloud', 'model_name': cloud.get('model_name') or 'gpt-4o-mini', 'configured': cloud_ok},
            {'id': 'local_teacher', 'model_name': local.get('model_name') or 'local-model',
             'teacher_model_name': cloud.get('model_name') or 'gpt-4o-mini',
             'configured': local_ok and cloud_ok}]}

    async def submit(self, payload: dict) -> dict:
        if self._closed:
            raise RuntimeError('browser task service is closed')
        if not isinstance(payload, dict) or set(payload) - {'task_id', 'executor', 'max_loop_steps', 'workflow_bundle'}:
            raise ValueError('unsupported browser task payload')
        task_id = payload.get('task_id')
        if type(task_id) is not str or task_id not in task_catalog():
            raise ValueError('unknown task_id')
        executor = payload.get('executor', 'local')
        if type(executor) is not str or executor not in {'local', 'cloud', 'local_teacher'}:
            raise ValueError('unsupported executor')
        steps = payload.get('max_loop_steps', 5)
        if type(steps) is not int or steps not in {5, 6}:
            raise ValueError('max_loop_steps must be 5 or 6')
        bundle = payload.get('workflow_bundle')
        digest = None
        if bundle is not None:
            if type(bundle) is not str or not Path(bundle).is_dir():
                raise ValueError('workflow_bundle must be a local directory')
            from core.computer_use.skills import BrowserSkillCatalog
            BrowserSkillCatalog.from_bundle(bundle)
            from core.evolution.mutator import bundle_digest
            bundle = str(Path(bundle).resolve())
            digest = bundle_digest(Path(bundle))
        task = task_catalog()[task_id]
        if executor == 'local_teacher' and not task.get('scoring_criteria'):
            raise ValueError('local_teacher requires an independent check')
        config = self._config()
        profiles, _ = _model_config(config, executor)
        job = self._lane.submit(task_type='browser_experiment', input_text=task['instruction'])
        run_id = job['job_id']
        self._deadlines[run_id] = time.monotonic() + self.RUN_DEADLINE_SECONDS
        self._requests[run_id] = {'task_id': task_id, 'executor': executor,
                                  'max_loop_steps': steps, 'workflow_bundle': bundle,
                                  'workflow_digest': digest, 'config': config,
                                  'model_name': profiles['primary'].provider.model_name,
                                  'teacher_model_name': profiles['teacher'].provider.model_name if profiles['teacher'] else None}
        self._worker.ensure_started()
        return self.get(run_id)

    def _public(self, job: dict | None) -> dict | None:
        if job is None:
            return None
        run_id = job['job_id']
        request = self._requests.get(run_id, {})
        execution = job['status']
        result = self._results.get(run_id) or job.get('result')
        status = ({'cancelled': 'stopped', 'completed': (result or {}).get('task_status', 'failed')}
                  .get(execution, execution))
        return {**job, 'result': result, 'error': (result or {}).get('error') or job.get('error'),
                'run_id': run_id, 'status': status, 'execution_status': execution,
                'task_id': request.get('task_id'), 'executor': request.get('executor'),
                'max_loop_steps': request.get('max_loop_steps')}

    def get(self, run_id: str) -> dict | None:
        return self._public(self._lane.get(run_id))

    def list(self) -> list[dict]:
        return [self._public(job) for job in self._lane.list()]

    async def _event(self, event, job):
        if self.on_event:
            await self.on_event(event, self._public(job))

    def _worker_finished(self, run_id, returncode):
        """Optional parent-side exit observation; default C5 behavior is unchanged."""

    async def _process(self, job):
        run_id = job['job_id']
        request = self._requests[run_id]
        spec = {**request, 'run_id': run_id, 'run_root': str(self.run_root)}
        python = os.environ.get('KAGE_BROWSER_PYTHON') or sys.executable
        deadline = self._deadlines[run_id]
        if self._lane.get(run_id)['status'] == 'cancelled':
            return self._partial(run_id, 'stopped', 'user_stop')
        startup = asyncio.create_task(asyncio.create_subprocess_exec(
            python, '-m', 'core.computer_use.task_bootstrap', str(self.run_root), run_id, *([self.WORKER_MODULE] if self.WORKER_MODULE != 'task_worker' else []), cwd=str(ROOT),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
        self._startups[run_id] = startup
        proc = None
        try:
            try:
                proc = await asyncio.wait_for(asyncio.shield(startup),
                                              timeout=max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                self._mark_stop(run_id)
                await self._terminate_startup(run_id, startup)
                result = self._partial(run_id, 'failed', 'timeout')
                self._save_partial(run_id, result)
                return result
            except Exception as exc:
                result = self._partial(run_id, 'failed', 'worker_launch_failed')
                error = f'WorkerLaunchError: {type(exc).__name__}: {exc}'
                secret = str((request.get('config', {}).get('model', {}).get('cloud_api') or {}).get('api_key') or '')
                result['error'] = error.replace(secret, '[REDACTED]') if secret else error
                self._save_partial(run_id, result)
                return result
            self._processes[run_id] = proc
            if self._lane.get(run_id)['status'] == 'cancelled':
                await self._kill(proc)
                return self._partial(run_id, 'stopped', 'user_stop')
            try:
                await asyncio.wait_for(proc.communicate(json.dumps(spec).encode()),
                                       timeout=max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                self._mark_stop(run_id)
                await self._kill(proc)
                result = self._partial(run_id, 'failed', 'timeout')
                self._save_partial(run_id, result)
                return result
            self._worker_finished(run_id, proc.returncode)
            path = self.run_root / f'run_{run_id}' / 'result.json'
            if path.exists():
                result = json.loads(path.read_text())
                if proc.returncode != 0:
                    partial = self._partial(run_id, 'failed', 'worker_crashed')
                    result = {**partial, **result, 'usage': partial['usage'],
                              'usage_status': partial['usage_status'], 'artifacts': partial['artifacts']}
            else:
                result = self._partial(run_id, 'failed', 'worker_crashed')
            if proc.returncode != 0:
                self._save_partial(run_id, result)
            return result
        except asyncio.CancelledError:
            self._mark_stop(run_id)
            if proc is None:
                await self._terminate_startup(run_id, startup)
            else:
                await self._kill(proc)
            raise
        finally:
            self._startups.pop(run_id, None)
            self._processes.pop(run_id, None)
            self._requests[run_id].pop('config', None)

    def _partial(self, run_id, status, reason):
        workspace = self.run_root / f'run_{run_id}'
        request = self._requests.get(run_id, {})
        task = task_catalog().get(request.get('task_id')) or {}
        executor = request.get('executor')
        traces = []
        teacher_requests = 0
        for trace_name in ('model-calls.jsonl', 'teacher-model-calls.jsonl'):
            path = workspace / trace_name
            if path.exists():
                for line in path.read_text(errors='replace').splitlines():
                    try:
                        item = json.loads(line)
                        traces.append(item)
                        if trace_name.startswith('teacher-') and 'request' in item:
                            teacher_requests += 1
                    except ValueError:
                        pass
        requests = sum('request' in item for item in traces)
        reported = [item['response']['usage'] for item in traces if 'response' in item
                    and all(key in item['response'].get('usage', {}) for key in ('input_tokens', 'output_tokens'))]
        usage = {'api_calls': requests, 'reported_calls': len(reported)}
        if reported:
            usage.update(reported_input_tokens=sum(item['input_tokens'] for item in reported),
                         reported_output_tokens=sum(item['output_tokens'] for item in reported))
        items = []
        if workspace.exists():
            for path in sorted(workspace.rglob('*')):
                if path.is_file() and not path.name.endswith('.tmp') and path.name != 'result.json':
                    name = str(path.relative_to(workspace))
                    items.append({'name': name, 'url': f'/api/browser/tasks/{run_id}/artifacts/{name}',
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        return {'task_status': status, 'run_status': reason, 'stop_reason': reason,
                'error': None if status == 'stopped' else reason,
                'check_available': bool(task.get('scoring_criteria')), 'check_passed': None,
                'executor': executor, 'model_name': request.get('model_name'),
                'teacher_model_name': request.get('teacher_model_name'),
                'teacher_triggered': bool(teacher_requests), 'teacher_used': bool(teacher_requests),
                'teacher_usage': {'api_calls': teacher_requests},
                'max_loop_steps': request.get('max_loop_steps'), 'usage': usage,
                'usage_status': 'partial_or_unknown' if requests else 'no_requests',
                'reservation': {'input_tokens': 120000 if executor == 'local_teacher' else 72000 if executor == 'cloud' else 48000,
                                'output_tokens': 8144 if executor == 'local_teacher' else 6144 if executor == 'cloud' else 2000,
                                'api_calls': 12 if executor == 'local_teacher' else 6},
                'cost': {'amount_usd': 0 if executor == 'local' else None,
                         'source': 'local_api_only' if executor == 'local' else 'unknown'},
                'workflow_digest': request.get('workflow_digest'), 'unpromoted': True,
                'artifacts': items, 'final_text': ''}

    def _save_partial(self, run_id, result):
        if (self._lane.get(run_id) or {}).get('status') == 'cancelled':
            return
        workspace = self.run_root / f'run_{run_id}'
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    def _mark_stop(self, run_id):
        workspace = self.run_root / f'run_{run_id}'
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / 'stop.requested').touch()

    def _owned_pid(self, run_id):
        path = self.run_root / f'run_{run_id}' / 'worker-owner.json'
        try:
            owner = json.loads(path.read_text())
            pid = owner['pid']
            return pid if type(pid) is int and pid > 0 and owner.get('pgid') == pid else None
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return None

    async def _terminate_startup(self, run_id, startup):
        limit = time.monotonic() + self.STARTUP_STOP_WAIT_SECONDS
        while True:
            if startup.done():
                try:
                    proc = startup.result()
                except Exception:
                    return
                await self._kill(proc)
                return
            pid = self._owned_pid(run_id)
            if pid is not None:
                self._reap_late_startup(startup)
                await self._kill_owned_pid(pid)
                return
            if time.monotonic() >= limit:
                self._reap_late_startup(startup)
                return
            await asyncio.sleep(.02)

    @staticmethod
    async def _kill_owned_pid(pid):
        # The bootstrap writes this PID only after creating its own process group.
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        limit = time.monotonic() + .5
        while time.monotonic() < limit:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(.02)
        # Chromium descendants can outlive the group leader.
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        limit = time.monotonic() + 1
        while time.monotonic() < limit:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(.02)
        raise RuntimeError('owned browser worker did not exit')

    def _reap_late_startup(self, startup):
        if startup in self._late_startups:
            return
        self._late_startups.add(startup)

        def settled(task):
            self._late_startups.discard(task)
            if task.cancelled():
                return
            try:
                proc = task.result()
            except Exception:
                return
            cleanup = asyncio.create_task(self._kill(proc))
            self._late_cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(self._late_cleanup_tasks.discard)

        startup.add_done_callback(settled)

    @staticmethod
    async def _kill(proc):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=.5)
        except asyncio.TimeoutError:
            pass
        # The group can outlive its leader (Chromium children).
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass

    async def stop(self, run_id: str) -> dict | None:
        job = self._lane.get(run_id)
        if job is None:
            return None
        if job['status'] in {'queued', 'running'}:
            self._mark_stop(run_id)
            cancelled = self._lane.cancel(run_id)
            startup = self._startups.get(run_id)
            proc = self._processes.get(run_id)
            if startup is not None:
                await self._terminate_startup(run_id, startup)
            elif proc:
                await self._kill(proc)
            result = self._partial(run_id, 'stopped', 'user_stop')
            self._results[run_id] = result
            workspace = self.run_root / f'run_{run_id}'
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            self._requests.get(run_id, {}).pop('config', None)
            await self._event('stopped', cancelled)
        return self.get(run_id)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        for job in self._lane.list():
            if job['status'] in {'queued', 'running'}:
                await self.stop(job['job_id'])
        await self._worker.stop()
        for request in self._requests.values():
            request.pop('config', None)

    def artifact(self, run_id: str, name: str):
        job = self._lane.get(run_id)
        if job is None or not isinstance(name, str) or not name or Path(name).is_absolute():
            return None
        workspace = (self.run_root / f'run_{run_id}').resolve()
        target = (workspace / name).resolve()
        if not target.is_relative_to(workspace) or not target.is_file():
            return None
        result = self._results.get(run_id) or job.get('result') or {}
        if name not in {item['name'] for item in result.get('artifacts', [])}:
            return None
        return target

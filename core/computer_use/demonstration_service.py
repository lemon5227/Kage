"""Durable teaching sessions on the existing owned, serial browser worker lane."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path
import time

from jsonschema import Draft202012Validator, ValidationError

from core.computer_use.demonstration import demonstration_tasks
from core.computer_use.skills import BrowserSkillCatalog
from core.computer_use.task_environment import atomic_json
from core.computer_use.task_service import BrowserTaskService

TERMINAL = {'verified', 'completed', 'incomplete', 'failed', 'stopped'}


class BrowserDemonstrationService(BrowserTaskService):
    WORKER_MODULE = 'demonstration_worker'
    RUN_DEADLINE_SECONDS = 900

    def __init__(self, run_root, config_loader, on_event=None):
        super().__init__(run_root, config_loader, on_event)
        self._history = {}
        self._recovery_errors = {}
        self._worker_exit_codes = {}
        for path in self.run_root.glob('run_*/session.json'):
            try:
                job = json.loads(path.read_text())
                run_id = job['run_id']
                if path.parent.name != 'run_' + run_id:
                    continue
                self._history[run_id] = job
                result = self._read(path.parent / 'result.json')
                accepted = self._accepted(run_id, result)
                marker = (path.parent / 'stop.requested').exists()
                deadline_failed = result.get('task_status') == 'failed' and result.get('stop_reason') == 'timeout'
                if not accepted or (marker and result.get('task_status') != 'stopped' and not deadline_failed):
                    self._recovery_path(run_id).touch()
                    self._mark_stop(run_id)
                    # Constructor recovery is bounded and synchronous: no new
                    # session or artifact index can precede owned-writer exit.
                    if self._recover_owner(run_id):
                        reason = result.get('stop_reason') if result.get('task_status') == 'stopped' else 'service_restart'
                        result = self._partial(run_id, 'stopped', reason or 'service_restart')
                        self._settle_result(run_id, result, clean_exit=False)
                    else:
                        self._recovery_errors[run_id] = 'RecoveryOwnershipUnverified: old worker cleanup did not complete'
                        result = {'task_status': 'stopped', 'stop_reason': 'service_restart',
                                  'error': self._recovery_errors[run_id], 'artifacts': [], 'event_count': 0}
                job['status'] = 'cancelled' if result.get('task_status') == 'stopped' else 'completed'
                self._results[run_id] = result
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def _recovery_path(self, run_id):
        return self.run_root / (run_id + '-recovery.requested')

    def _acceptance_path(self, run_id):
        # Keep mutable parent control metadata outside archived run evidence.
        return self.run_root / (run_id + '-acceptance.json')

    def _accepted(self, run_id, result):
        acceptance = self._read(self._acceptance_path(run_id))
        path = self.run_root / ('run_' + run_id) / 'result.json'
        return (result.get('task_status') in TERMINAL and acceptance.get('settled') is True
                and acceptance.get('run_id') == run_id and acceptance.get('task_status') == result['task_status']
                and (result['task_status'] not in {'verified', 'completed'} or acceptance.get('clean_worker_exit') is True)
                and path.is_file() and acceptance.get('result_sha256') == hashlib.sha256(path.read_bytes()).hexdigest())

    def _settle_result(self, run_id, result, *, clean_exit):
        path = self.run_root / ('run_' + run_id) / 'result.json'
        atomic_json(path, result)
        atomic_json(self._acceptance_path(run_id), {'run_id': run_id, 'settled': True,
            'clean_worker_exit': clean_exit, 'task_status': result['task_status'],
            'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    @staticmethod
    def _pid_alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _recover_owner(self, run_id):
        pid = self._owned_pid(run_id)
        if pid is None:
            workspace = self.run_root / ('run_' + run_id)
            return not (workspace / 'worker-owner.json').exists() and not (workspace / 'initial-observation.json').exists()
        if not self._pid_alive(pid):
            return True
        try:
            owner = self._read(self.run_root / ('run_' + run_id) / 'worker-owner.json')
            command = subprocess.check_output(['ps', '-ww', '-p', str(pid), '-o', 'command='],
                                              text=True, timeout=.5).strip()
            if (os.getpgid(pid) != pid or owner.get('run_id', run_id) != run_id
                    or owner.get('run_root', str(self.run_root)) != str(self.run_root)
                    or run_id not in command or str(self.run_root) not in command
                    or 'core.computer_use.task_bootstrap' not in command):
                return False
            # Let a cooperative recorder disable listening and flush pending
            # input. Noncooperative/suspended groups get bounded TERM/KILL.
            for duration, action in ((1., None), (.5, signal.SIGTERM), (.5, signal.SIGKILL)):
                if action is not None:
                    try:
                        os.killpg(pid, action)
                        if action == signal.SIGTERM:
                            os.killpg(pid, signal.SIGCONT)
                    except ProcessLookupError:
                        # A dead group can still have an unreaped leader. Keep
                        # waiting for the PID rather than assuming it is gone.
                        pass
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    if not self._pid_alive(pid):
                        if action is not None:
                            try:
                                os.killpg(pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        return True
                    time.sleep(.02)
            # An owned child can be a zombie if its former async parent has
            # not processed exit yet. Reap only this validated PID if possible.
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            return not self._pid_alive(pid)
        except ProcessLookupError:
            return not self._pid_alive(pid)
        except (OSError, subprocess.SubprocessError):
            return not self._pid_alive(pid)

    @staticmethod
    def _read(path):
        try:
            value = json.loads(path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def catalog(self):
        return {'tasks': [{'task_id': t['task_id'], 'title': t['fixture']['title'],
                           'family': t['family'], 'instruction': t['instruction'], 'check_available': True}
                          for t in demonstration_tasks().values()],
                'sources': ['human_declared', 'automation'], 'model_requests': 0}

    def _active(self):
        return any(job['status'] not in TERMINAL for job in self.list())

    async def _submit(self, task_id, source, operation, **extra):
        if self._closed:
            raise RuntimeError('browser demonstration service is closed')
        if self._recovery_errors:
            raise RuntimeError('old browser worker recovery is incomplete')
        if self._active():
            raise RuntimeError('a browser demonstration session is already active')
        task = demonstration_tasks()[task_id]
        job = self._lane.submit(task_type='browser_demonstration', input_text=task['instruction'])
        run_id = job['job_id']
        request = {'task_id': task_id, 'source_kind': source, 'operation': operation,
                   'executor': source if operation == 'demonstration' else 'workflow_engine', 'config': {}, **extra}
        self._requests[run_id] = request
        self._deadlines[run_id] = time.monotonic() + min(self.RUN_DEADLINE_SECONDS, 900 if operation == 'demonstration' else 480)
        workspace = self.run_root / ('run_' + run_id)
        workspace.mkdir()
        public = {**job, **{k: v for k, v in request.items() if k not in {'config', 'candidate', 'arguments'}},
                  'run_id': run_id}
        atomic_json(workspace / 'session.json', public)
        self._worker.ensure_started()
        return self.get(run_id)

    async def submit(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'task_id', 'source_kind'}:
            raise ValueError('unsupported demonstration payload')
        task_id = payload.get('task_id')
        source = payload.get('source_kind', 'human_declared')
        if type(task_id) is not str or task_id not in {'demo_profile', 'demo_preferences'}:
            raise ValueError('unknown teaching task_id')
        if type(source) is not str or source not in {'human_declared', 'automation'}:
            raise ValueError('unsupported source_kind')
        return await self._submit(task_id, source, 'demonstration')

    def _public(self, job):
        if job is None:
            return None
        run_id = job.get('run_id') or job['job_id']
        request = self._requests.get(run_id) or job
        workspace = self.run_root / ('run_' + run_id)
        state = self._read(workspace / 'status.json')
        result = self._results.get(run_id) or job.get('result') or self._read(workspace / 'result.json') or None
        execution = job['status']
        status = (result or {}).get('task_status') or ('starting' if execution == 'running' else execution)
        if status not in TERMINAL and state.get('status'):
            status = state['status']
        if execution in {'queued', 'running'} and status in TERMINAL and status != 'stopped':
            status = 'finalizing'
        deadline_failed = result and result.get('task_status') == 'failed' and result.get('stop_reason') == 'timeout'
        if ((workspace / 'stop.requested').exists() and not self._recovery_path(run_id).exists()
                and execution not in {'queued', 'running'} and not deadline_failed):
            # Stop is authoritative even if a killed process published late bytes.
            if not result or result.get('task_status') != 'stopped':
                result = self._partial(run_id, 'stopped', 'user_stop')
            status = 'stopped'
        if self._recovery_path(run_id).exists():
            if not result or result.get('task_status') != 'stopped':
                result = {'task_status': 'stopped', 'stop_reason': 'service_restart',
                          'error': None, 'artifacts': [], 'event_count': state.get('event_count', 0)}
            status = 'stopped'
        return {**job, 'task_type': 'browser_demonstration', 'run_id': run_id, 'status': status,
                'execution_status': execution, 'operation': request.get('operation'),
                'task_id': request.get('task_id'), 'source_kind': request.get('source_kind'),
                'executor': request.get('executor'), 'ready': status == 'recording' and state.get('ready', False),
                'automation_cdp_endpoint': state.get('automation_cdp_endpoint') if request.get('source_kind') == 'automation' and status == 'recording' else None,
                'event_count': (result or {}).get('event_count', state.get('event_count', 0)),
                'check_available': True, 'check_passed': (result or {}).get('check_passed'),
                'stop_reason': (result or {}).get('stop_reason'), 'error': (result or {}).get('error') or job.get('error'),
                'result': result, 'artifacts': (result or {}).get('artifacts', [])}

    def _worker_finished(self, run_id, returncode):
        self._worker_exit_codes[run_id] = returncode

    def _save_partial(self, run_id, result):
        if not self._recovery_path(run_id).exists():
            super()._save_partial(run_id, result)

    async def _process(self, job):
        result = await super()._process(job)
        run_id = job['job_id']
        exit_code = self._worker_exit_codes.pop(run_id, None)
        if self._recovery_path(run_id).exists():
            # The recovering parent owns publication. An old parent's delayed
            # callback cannot overwrite its accepted restart snapshot.
            result = self._partial(run_id, 'stopped', 'service_restart')
            self._results[run_id] = result
            return result
        cancelled = (self._lane.get(run_id) or {}).get('status') == 'cancelled'
        marker = (self.run_root / ('run_' + run_id) / 'stop.requested').exists()
        deadline_failed = result.get('task_status') == 'failed' and result.get('stop_reason') == 'timeout'
        if cancelled or (marker and not deadline_failed):
            persisted = self._read(self.run_root / ('run_' + run_id) / 'result.json')
            reason = persisted.get('stop_reason') if persisted.get('task_status') == 'stopped' else 'user_stop'
            result = self._partial(run_id, 'stopped', reason or 'user_stop')
        elif (exit_code is not None and exit_code != 0) or result.get('run_status') == 'worker_crashed':
            result.update(task_status='failed', error='worker_crashed', stop_reason='worker_crashed')
            result.pop('candidate', None)
        # super has reaped the child/owned startup and released its handles.
        # There is no await between cancellation check and durable acceptance.
        clean_exit = not marker and exit_code == 0
        self._settle_result(run_id, result, clean_exit=clean_exit)
        self._results[run_id] = result
        return result

    def get(self, run_id):
        return self._public(self._lane.get(run_id) or self._history.get(run_id))

    def list(self):
        current = {job['job_id']: job for job in self._lane.list()}
        return [self._public(job) for job in {**self._history, **current}.values()]

    async def finish(self, run_id):
        job = self.get(run_id)
        if job is None or job['status'] in TERMINAL:
            return job
        if job['operation'] != 'demonstration' or job['status'] not in {'recording', 'finalizing'}:
            raise RuntimeError('session is not ready to finish')
        (self.run_root / ('run_' + run_id) / 'finish.requested').touch()
        return self.get(run_id)

    async def replay(self, run_id, payload):
        job = self.get(run_id)
        if job is None:
            raise LookupError('browser demonstration not found')
        if not isinstance(payload, dict) or set(payload) != {'task_id', 'arguments'}:
            raise ValueError('replay requires task_id and arguments')
        task_id = payload['task_id']
        if type(task_id) is not str or task_id not in {'reuse_profile', 'reuse_preferences'}:
            raise ValueError('unknown replay task_id')
        if job['status'] != 'verified' or job['operation'] != 'demonstration':
            raise RuntimeError('replay requires a verified complete candidate')
        tasks = demonstration_tasks()
        if tasks[task_id]['family'] != tasks[job['task_id']]['family']:
            raise RuntimeError('candidate family does not match replay task')
        candidate = job['result'].get('candidate')
        workspace = (self.run_root / ('run_' + run_id)).resolve()
        try:
            bundle = Path(candidate['bundle_path']).resolve()
            if bundle != workspace / 'candidate':
                raise ValueError('invalid candidate path')
            catalog = BrowserSkillCatalog.from_bundle(bundle)
            if catalog.digests.get(candidate['skill_id']) != candidate['digest']:
                raise ValueError('candidate digest mismatch')
            for name, digest in candidate['source_hashes'].items():
                path = (workspace / name).resolve()
                if not path.is_relative_to(workspace) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('candidate source hash mismatch')
            for item in job['result']['artifacts']:
                if item['name'].startswith('candidate/'):
                    path = (workspace / item['name']).resolve()
                    if not path.is_relative_to(workspace) or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                        raise ValueError('candidate artifact hash mismatch')
            schema = json.loads((bundle / 'manifest.json').read_text())['skills'][0]['parameters']
            Draft202012Validator(schema).validate(payload['arguments'])
        except ValidationError as exc:
            raise ValueError('invalid replay arguments: ' + exc.message) from None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('candidate unavailable or changed: ' + str(exc)) from None
        return await self._submit(task_id, job['source_kind'], 'replay', candidate=candidate,
                                  arguments=payload['arguments'], source_run_id=run_id)

    def _partial(self, run_id, status, reason):
        workspace = self.run_root / ('run_' + run_id)
        state = self._read(workspace / 'status.json')
        count = state.get('event_count', 0)
        events = workspace / 'demonstration-events.jsonl'
        if events.exists():
            count = max(count, len(events.read_text(errors='replace').splitlines()))
        from core.computer_use.demonstration_worker import artifacts
        return {'task_status': status, 'run_status': reason, 'stop_reason': reason,
                'error': None if status == 'stopped' else reason, 'check_available': True,
                'check_passed': None, 'event_count': count,
                'usage': {'api_calls': 0}, 'usage_status': 'no_requests', 'unpromoted': True,
                'cost': {'amount_usd': 0, 'source': 'local_api_only'}, 'artifacts': artifacts(workspace, run_id)}

    async def stop(self, run_id):
        job = self.get(run_id)
        if job is None or job['status'] in TERMINAL:
            return job
        stopped = await super().stop(run_id)
        self._settle_result(run_id, stopped['result'], clean_exit=False)
        return stopped

    def artifact(self, run_id, name):
        job = self.get(run_id)
        if job is None or not isinstance(name, str) or not name or Path(name).is_absolute():
            return None
        workspace = (self.run_root / ('run_' + run_id)).resolve()
        target = (workspace / name).resolve()
        if not target.is_relative_to(workspace) or not target.is_file():
            return None
        return target if name in {item['name'] for item in job['artifacts']} else None

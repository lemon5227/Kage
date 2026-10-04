"""One browser experiment in a managed subprocess; private settings arrive on stdin."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from core.computer_use.experiment import BrowserChainProvider, BrowserCloudProvider
from core.computer_use.skills import BrowserSkillCatalog
from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
from core.computer_use.task_environment import atomic_json
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.runner import EvolutionRunner
from core.model_broker import ModelBroker
from core.model_provider import ModelProvider, ModelResponse

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'eval/computer-use/browser-learning-v2.json'


def task_catalog() -> dict[str, dict[str, Any]]:
    tasks = json.loads(SUITE.read_text())['tasks']
    selected = {task['task_id']: task for task in tasks if task['task_id'] in {'profile_dev', 'preferences_dev'}}
    unchecked = json.loads(json.dumps(selected['preferences_dev']))
    unchecked['task_id'] = 'preferences_unchecked'
    unchecked.pop('scoring_criteria', None)
    selected[unchecked['task_id']] = unchecked
    return selected


def _model_config(config: dict, executor: str) -> tuple[dict, dict]:
    effective = json.loads(json.dumps(config))
    model = effective.setdefault('model', {})
    cloud = model.get('cloud_api') or {}
    if executor in {'local', 'local_teacher'}:
        local = model.get('local_runtime')
        if (not isinstance(local, dict) or not isinstance(local.get('host'), str)
                or not local['host'].strip() or type(local.get('port')) is not int
                or not 1 <= local['port'] <= 65535):
            raise ValueError('model.local_runtime requires explicit host and port')
    if executor in {'cloud', 'local_teacher'}:
        if str(cloud.get('provider_type') or 'openai').lower() not in {'openai', 'openai-compatible'}:
            raise ValueError('cloud requires an OpenAI-compatible provider')
        from urllib.parse import urlparse
        import ipaddress
        base = str(cloud.get('base_url') or 'https://api.openai.com/v1')
        parsed = urlparse(base)
        host = parsed.hostname or ''
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == 'localhost' or host.endswith('.localhost')
        if parsed.scheme != 'https' or not host or loopback:
            raise ValueError('cloud requires a remote HTTPS endpoint')
        if not str(cloud.get('api_key') or '').strip():
            raise ValueError('cloud credential is missing')
    model['hybrid'] = {'enabled': False}
    broker = model.setdefault('broker', {})
    broker['background_provider'] = 'cloud' if executor == 'cloud' else 'local'
    broker['fallback_provider'] = 'cloud'
    instance = ModelBroker(effective)
    primary = instance.profile('background')
    expected = 'cloud' if executor == 'cloud' else 'local'
    if primary.mode != expected:
        raise ValueError('selected executor did not resolve to expected provider mode')
    teacher = instance.profile('fallback_cloud') if executor == 'local_teacher' else None
    if teacher is not None and teacher.mode != 'cloud':
        raise ValueError('teacher did not resolve to cloud')
    return {'primary': primary, 'teacher': teacher}, effective


class RecordedProvider(ModelProvider):
    """Keep requests and provider responses as evidence without private credentials."""
    def __init__(self, provider: ModelProvider, path: Path, secrets: list[str], *, remote=False):
        self.provider, self.path = provider, path
        self.remote = remote
        self.secrets = [secret for secret in secrets if secret]

    def _redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                escaped = json.dumps(secret, ensure_ascii=False)[1:-1]
                value = value.replace(escaped, '[REDACTED]').replace(secret, '[REDACTED]')
            return value
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value

    def _record(self, value):
        line = json.dumps(self._redact(value), ensure_ascii=False, default=str)
        with self.path.open('a') as stream:
            stream.write(line + '\n')

    def generate(self, messages, **kwargs):
        if self.remote:
            kwargs = {**kwargs, 'temperature': 0, 'max_tokens': 1024}
            self.provider.thinking = False
            wire = self.provider._serialize_request(self.provider._request_payload(messages, **kwargs))
            if len(wire) > 12000:
                self._record({'error': 'remote input byte cap reached', 'wire_bytes': len(wire)})
                raise RuntimeError('remote input byte cap reached')
        self._record({'request': {'messages': messages, **kwargs}})
        try:
            response = self.provider.generate(messages=messages, **kwargs)
        except Exception as exc:
            safe_error = self._redact(f'{type(exc).__name__}: {exc}')
            self._record({'error': safe_error})
            raise RuntimeError(safe_error) from None
        safe_response = ModelResponse(**self._redact(asdict(response)))
        self._record({'response': asdict(safe_response)})
        return safe_response


def _artifacts(workspace: Path, run_id: str) -> list[dict]:
    return [{'name': str(path.relative_to(workspace)),
             'url': f'/api/browser/tasks/{run_id}/artifacts/{path.relative_to(workspace)}',
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(workspace.rglob('*')) if path.is_file() and not path.name.endswith('.tmp') and path.name != 'result.json']


def run(request: dict) -> dict:
    run_id = request['run_id']
    root = Path(request['run_root'])
    workspace = root / f'run_{run_id}'
    workspace.mkdir(parents=True, exist_ok=True)
    task = task_catalog()[request['task_id']]
    executor = request['executor']
    profiles, effective = _model_config(request['config'], executor)
    primary, teacher = profiles['primary'], profiles['teacher']
    secrets = [str((effective.get('model') or {}).get('cloud_api', {}).get('api_key') or '')]
    model = RecordedProvider(primary.provider, workspace / 'model-calls.jsonl', secrets, remote=executor == 'cloud')
    kwargs = dict(model_label=primary.provider.model_name, provider_label=type(primary.provider).__name__,
                  max_model_calls=6, external_completion=bool(task.get('scoring_criteria')),
                  observation_format='compact-v2', max_loop_steps=request['max_loop_steps'],
                  browser_skill_bundle=request.get('workflow_bundle'))
    if executor == 'cloud':
        provider = BrowserCloudProvider(model, task, **kwargs)
    elif executor == 'local_teacher':
        teacher_model = RecordedProvider(teacher.provider, workspace / 'teacher-model-calls.jsonl', secrets, remote=True)
        provider = BrowserTeacherTakeoverProvider(model, teacher_model, task, teacher_label=teacher.provider.model_name,
                                                  max_teacher_calls=6, teacher_output_tokens=1024,
                                                  teacher_context_pack=True, **kwargs)
    else:
        provider = BrowserChainProvider(model, task, **kwargs)
    digest = None
    if request.get('workflow_bundle'):
        BrowserSkillCatalog.from_bundle(request['workflow_bundle'])
        digest = bundle_digest(Path(request['workflow_bundle']))
    journal = Journal(root / f'{run_id}-journal.sqlite')
    budget = BudgetTracker(BudgetConfig(max_api_calls=12, max_input_tokens_total=300000,
                                        max_output_tokens_total=30000,
                                        input_cost_per_million=0, output_cost_per_million=0),
                           root / f'{run_id}-budget.sqlite')
    runner = EvolutionRunner(journal, budget, root, provider, step_isolation='inline')
    candidate = Candidate('browser-task', (), 'workflow', str(ROOT), digest or 'unpromoted')
    completed = runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id, task['task_id'],
                                                     max_steps=1, timeout_s=480))
    chain = (completed.metadata.get('chain') or [{}])[-1]
    student_calls = list(provider._model.calls)
    teacher_calls = list(provider._teacher.calls) if executor == 'local_teacher' else []
    calls = student_calls + teacher_calls
    usage = {'api_calls': len(calls)}
    if calls and all('input_tokens' in call['usage'] and 'output_tokens' in call['usage'] for call in calls):
        usage.update(input_tokens=sum(call['usage']['input_tokens'] for call in calls),
                     output_tokens=sum(call['usage']['output_tokens'] for call in calls))
        usage_status = 'reported'
    elif not calls:
        usage_status = 'no_requests'
    else:
        usage_status = 'partial_or_unknown'
    check_available = bool(task.get('scoring_criteria'))
    model_errors = [call['error'] for call in calls if call.get('error')]
    execution_failed = (completed.status in {'crashed', 'timeout', 'budget_exhausted'}
                        or chain.get('stop_reason') == 'call_error' or bool(model_errors))
    check_passed = (completed.status == 'passed' if check_available else None)
    if execution_failed and not check_passed:
        check_passed = None
    task_status = ('completed' if check_passed else 'failed' if execution_failed or check_available else 'unknown')
    cost = {'amount_usd': 0 if executor == 'local' else None,
            'source': 'local_api_only' if executor == 'local' else 'unknown_unpriced'}
    cloud = (effective.get('model') or {}).get('cloud_api') or {}
    cloud_calls = calls if executor == 'cloud' else teacher_calls
    input_rate, output_rate = cloud.get('input_cost_per_million'), cloud.get('output_cost_per_million')
    if executor != 'local' and input_rate is not None and output_rate is not None and usage_status == 'reported':
        try:
            cost = {'amount_usd': round((sum(c['usage']['input_tokens'] for c in cloud_calls) * float(input_rate) +
                                         sum(c['usage']['output_tokens'] for c in cloud_calls) * float(output_rate)) / 1_000_000, 8),
                    'source': 'configured_rates'}
        except (TypeError, ValueError):
            pass
    result = {'task_status': task_status, 'check_available': check_available,
              'check_passed': check_passed, 'run_status': completed.status,
              'error': model_errors[0] if model_errors and not check_passed else None,
              'model_errors': model_errors,
              'stop_reason': ('model_error' if model_errors and not check_passed else
                              chain.get('stop_reason') or completed.metadata.get('completion', {}).get('stop_reason')),
              'executor': executor, 'model_name': primary.provider.model_name,
              'teacher_model_name': teacher.provider.model_name if teacher else None,
              'teacher_triggered': bool(chain.get('takeover', {}).get('triggered')) if teacher else False,
              'teacher_used': bool(teacher_calls),
              'teacher_usage': {'api_calls': len(teacher_calls),
                                **({'input_tokens': sum(c['usage']['input_tokens'] for c in teacher_calls),
                                    'output_tokens': sum(c['usage']['output_tokens'] for c in teacher_calls)}
                                   if teacher_calls and all('input_tokens' in c['usage'] and 'output_tokens' in c['usage']
                                                            for c in teacher_calls) else {})},
              'max_loop_steps': request['max_loop_steps'], 'usage': usage, 'usage_status': usage_status,
              'reservation': {'input_tokens': provider.RESERVATION_INPUT_CAP,
                              'output_tokens': provider.RESERVATION_OUTPUT_CAP,
                              'api_calls': 12 if teacher else 6},
              'cost': cost, 'workflow_digest': digest, 'unpromoted': True,
              'final_text': chain.get('final_text', ''), 'artifacts': _artifacts(workspace, run_id)}
    atomic_json(workspace / 'result.json', result)
    return result


def main():
    try:
        request = json.loads(sys.stdin.buffer.read())
        if (Path(request['run_root']) / f"run_{request['run_id']}" / 'stop.requested').exists():
            return
        run(request)
    except BaseException as exc:
        # Never echo private configuration on stdout/stderr.
        try:
            workspace = Path(request['run_root']) / f"run_{request['run_id']}"
            workspace.mkdir(parents=True, exist_ok=True)
            secret = str((request.get('config', {}).get('model', {}).get('cloud_api') or {}).get('api_key') or '')
            error = f'{type(exc).__name__}: {exc}'
            if secret:
                error = error.replace(secret, '[REDACTED]')
            atomic_json(workspace / 'result.json', {'task_status': 'failed', 'error': error,
                                                     'run_status': 'crashed', 'usage_status': 'unknown'})
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == '__main__':
    main()

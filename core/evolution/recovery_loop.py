"""Single-worker persistent recovery learning; execution/scoring remain in Promoter."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from core.evolution.artifacts import atomic_json
from core.evolution.agent_provider import has_infrastructure_model_errors
from core.evolution.bundle import RecoveryPolicy
from core.evolution.contracts import Candidate, EvolutionEvent
from core.evolution.mutator import bundle_digest
from core.evolution.skills import SkillCatalog


def _candidate(data):
    return Candidate(**{**data, 'parent_ids': tuple(data['parent_ids'])})


def _runtime_fault(result):
    for chain in result.metadata.get('chain', []):
        for event in chain.get('recovery_events', []):
            if event.get('error'):
                return True
        for event in chain.get('recovery_trace', []):
            response = event.get('result', {})
            if isinstance(response, dict) and (response.get('error') or response.get('traceback')):
                return True
    return False


def classify_failure(result):
    if result.status == 'budget_exhausted':
        return 'budget'
    if result.status in {'timeout', 'crashed'}:
        return 'infrastructure'
    for chain in result.metadata.get('chain', []):
        if has_infrastructure_model_errors(chain.get('model_errors', [])) or chain.get('tool_action_limit_reached'):
            return 'infrastructure'
        for error in chain.get('tool_errors', []):
            kind = str(error.get('error_type', '')).lower()
            message = str(error.get('error_message', '')).lower()
            if error.get('outcome') in {'denied', 'needs_confirmation'} or any(
                marker in kind + ' ' + message for marker in ('permissionerror', 'permission denied',
                    'timeouterror', 'connectionerror', 'connection reset', 'service unavailable')):
                return 'infrastructure'
        reason = str(chain.get('stop_reason', '')).lower()
        if any(word in reason for word in ('budget', 'max_steps', 'step_limit', 'call_limit', 'timeout', 'deadline', 'cancel', 'permission')):
            return 'resource_or_infrastructure'
    if result.trace_path and Path(result.trace_path).exists():
        for line in Path(result.trace_path).read_text().splitlines():
            observation = json.loads(line).get('observation', {})
            if observation.get('success') is False or observation.get('status') == 'error':
                error = str(observation.get('content', '')).lower()
                if observation.get('outcome') in {'denied', 'needs_confirmation'} or any(
                    marker in error for marker in ('permissionerror', 'permission denied', 'timeouterror',
                        'connectionerror', 'connection reset', 'service unavailable', 'tool action budget exhausted')):
                    return 'infrastructure'
    return 'capability' if result.status == 'failed' else 'none' 


def visible_feedback(task, result):
    """Only public goal and actual machine observations cross the teacher boundary."""
    trace = []
    for line in Path(result.trace_path).read_text().splitlines():
        row = json.loads(line)
        visible = {'step': row.get('step')}
        if isinstance(row.get('action'), dict) and row['action'].get('name') != 'finish':
            visible['action'] = {key: row['action'][key] for key in ('name', 'arguments', 'path', 'content') if key in row['action']}
        if isinstance(row.get('observation'), dict):
            visible['observation'] = {key: row['observation'][key] for key in ('status', 'outcome', 'success', 'content', 'actor') if key in row['observation']}
        if 'action' in visible or 'observation' in visible:
            trace.append(visible)
    return {'task_id': task['task_id'], 'instruction': task.get('instruction', ''),
            'failure_reason': 'external dev evaluator rejected output', 'trace': trace}


class RecoveryLoop:
    """Durable bounded loop. Caller supplies the existing configured execution boundary.

    A task identity is immutable and executed at most once. Interrupted reservations
    stay spent: a restart never replays possible side effects or regenerates a slot.
    """
    def __init__(self, promoter, mutator_factory, root, bootstrap_candidate,
                 validation_tasks, max_candidates=2, max_evaluations=12):
        if not 1 <= max_candidates <= 2 or not 1 <= max_evaluations <= 12:
            raise ValueError('G1 caps are 2 candidates and 12 evaluations')
        if not validation_tasks or any(t.get('split') != 'validation' for t in validation_tasks):
            raise ValueError('explicit isolated validation tasks required')
        if len({t['task_id'] for t in validation_tasks}) != len(validation_tasks):
            raise ValueError('duplicate validation IDs')
        self.promoter, self.mutator_factory = promoter, mutator_factory
        self.root = Path(root)
        if self.root.resolve() != promoter.root.resolve():
            raise ValueError('loop and promoter must share active root')
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root/'recovery_state.json'
        self.bootstrap = bootstrap_candidate
        self.validation_tasks = validation_tasks
        self.max_candidates, self.max_evaluations = max_candidates, max_evaluations
        protocol = json.loads(json.dumps({'bootstrap': asdict(bootstrap_candidate), 'validation_tasks': validation_tasks,
                    'max_candidates': max_candidates, 'max_evaluations': max_evaluations}))
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            'protocol': protocol, 'candidates': 0, 'evaluations': 0, 'tasks': {}, 'disabled': [],
            'last_verified_parent': asdict(bootstrap_candidate), 'verified': [json.loads(json.dumps(asdict(bootstrap_candidate)))],
            'task_fingerprints': {}}
        if self.state['protocol'] != protocol:
            raise ValueError('persistent recovery protocol changed')
        self._save()

    def _save(self):
        atomic_json(self.state_path, self.state)

    def _validate(self, candidate):
        if candidate.target != 'recovery' or bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
            raise ValueError('recovery candidate bundle digest mismatch')
        SkillCatalog.from_bundle(Path(candidate.bundle_path))
        RecoveryPolicy.from_bundle(candidate.bundle_path)
        manifest = json.loads((Path(candidate.bundle_path)/'manifest.json').read_text())
        base = json.loads((Path(self.bootstrap.bundle_path)/'manifest.json').read_text())
        if manifest.get('skills') != base.get('skills'):
            raise ValueError('recovery evolution must preserve frozen skills')

    def _disabled_digests(self):
        return {row['candidate']['digest'] for row in self.state['disabled'] if row.get('candidate')}

    def _known(self, candidate):
        return json.loads(json.dumps(asdict(candidate))) in self.state['verified']

    def _remember(self, candidate):
        if not self._known(candidate):
            self.state['verified'].append(json.loads(json.dumps(asdict(candidate))))

    def _disable(self, candidate, reason):
        self.state['disabled'].append({'candidate': asdict(candidate) if candidate else None, 'reason': reason})
        self._save()  # disabling is authoritative even if pointer publication is interrupted
        fallback = None
        for data in reversed(self.state['verified']):
            possible = _candidate(data)
            if possible.digest in self._disabled_digests():
                continue
            try:
                self._validate(possible)
            except Exception as exc:
                self.state['disabled'].append({'candidate': data, 'reason': f'invalid verified ancestor: {exc}'})
                self._save()
                continue
            fallback = possible
            break
        if fallback is None:
            raise ValueError('no eligible verified recovery ancestor; stop without execution')
        ancestry = [data for data in self.state['verified']
                    if data['digest'] not in self._disabled_digests() and data['digest'] != fallback.digest]
        self.state['last_verified_parent'] = ancestry[-1] if ancestry else asdict(fallback)
        atomic_json(self.root/'active.json', {'candidate': asdict(fallback),
            'last_verified_parent': self.state['last_verified_parent']})
        self._save()
        self.promoter.journal.record_event(EvolutionEvent('rollback-'+str(len(self.state['disabled'])),
            candidate.candidate_id if candidate else 'invalid-active', '', 0, 'rollback', {'reason': reason, 'fallback': asdict(fallback)}))
        return fallback

    def load_active(self):
        candidate = None
        try:
            active_path = self.root/'active.json'
            if active_path.exists():
                data = json.loads(active_path.read_text())
                candidate = _candidate(data['candidate'])
                if not self._known(candidate):
                    comparison_id = data.get('comparison_id', '')
                    if not isinstance(comparison_id, str) or len(comparison_id) != 64 or any(c not in '0123456789abcdef' for c in comparison_id):
                        raise ValueError('active candidate lacks verified promotion provenance')
                    comparison = json.loads((self.root/'comparisons'/f'{comparison_id}.json').read_text())
                    digest = hashlib.sha256(json.dumps(comparison, sort_keys=True).encode()).hexdigest()
                    parent = _candidate(comparison['parent'])
                    if digest != comparison_id or comparison.get('promoted') is not True or not self._known(parent):
                        raise ValueError('active promotion provenance invalid')
                    if comparison.get('child') != json.loads(json.dumps(asdict(candidate))) or parent.candidate_id not in candidate.parent_ids:
                        raise ValueError('active promotion child/lineage mismatch')
                    expected_ids = [task['task_id'] for task in self.validation_tasks]
                    if [pair['task_id'] for pair in comparison.get('pairs', [])] != expected_ids or any(
                        not pair[arm]['run_id'].startswith('validation-') for pair in comparison['pairs'] for arm in ('parent','child')):
                        raise ValueError('active promotion did not use frozen validation')
                    self._validate(parent)
                    if parent.digest in self._disabled_digests():
                        raise ValueError('promotion descended from disabled parent')
                    self._remember(candidate)
                    self.state['last_verified_parent'] = asdict(parent)
            else:
                candidate = _candidate(self.state['verified'][-1])
            self._validate(candidate)
            if candidate.digest in self._disabled_digests():
                raise ValueError('active recovery version is disabled')
            self._save()
            return candidate
        except Exception as exc:
            return self._disable(candidate, f'{type(exc).__name__}: {exc}')

    def run_task(self, task):
        if task.get('split') not in {'dev', 'reuse', 'test'}:
            raise ValueError('continuous tasks require explicit dev/reuse/test split')
        if task['task_id'] in {t['task_id'] for t in self.validation_tasks}:
            raise ValueError('validation task cannot enter learning stream')
        key = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()
        prior = self.state['task_fingerprints'].get(task['task_id'])
        if prior is not None and prior != key:
            raise ValueError('task_id payload changed; possible side effects cannot be replayed')
        if key in self.state['tasks']:
            return self.state['tasks'][key]
        candidate = self.load_active()
        report = {'candidate': json.loads(json.dumps(asdict(candidate))), 'result': None, 'comparison': None,
                  'failure_kind': 'none', 'stop_reason': 'interrupted'}
        self.state['tasks'][key] = report
        self.state['task_fingerprints'][task['task_id']] = key
        if self.state['evaluations'] >= self.max_evaluations:
            report['stop_reason'] = 'evaluation_limit'
            self._save()
            return report
        self.state['evaluations'] += 1
        self._save()  # reserve BEFORE any execution
        result = self.promoter.evaluate(candidate, task)
        report['result'] = asdict(result)
        report['failure_kind'] = classify_failure(result)
        report['stop_reason'] = report['failure_kind']
        if _runtime_fault(result):
            try:
                self._disable(candidate, 'runtime recovery fault; current task is not replayed')
                report['stop_reason'] = 'runtime_rollback'
            except ValueError as exc:
                report['stop_reason'] = 'no_verified_parent'
                report['rollback_error'] = str(exc)
        elif task['split'] == 'dev' and report['failure_kind'] == 'capability':
            required = 2 * len(self.validation_tasks)
            if self.state['candidates'] >= self.max_candidates:
                report['stop_reason'] = 'candidate_limit'
            elif self.state['evaluations'] + required > self.max_evaluations:
                report['stop_reason'] = 'evaluation_limit'
            else:
                report['stop_reason'] = 'interrupted'
                slot = self.state['candidates']
                self.state['candidates'] += 1
                self.state['evaluations'] += required
                self._save()  # abandoned proposal/paired runs remain spent after restart
                try:
                    child = self.mutator_factory(self.root/'mutations'/f'slot-{slot}').propose(candidate, visible_feedback(task, result))
                    self._validate(child)
                    report['comparison'] = self.promoter.compare(candidate, child, self.validation_tasks, promotion_split='validation')
                    if report['comparison']['promoted']:
                        self._remember(child)
                        self.state['last_verified_parent'] = asdict(candidate)
                    report['stop_reason'] = 'promoted' if report['comparison']['promoted'] else 'rejected'
                except Exception as exc:
                    report['stop_reason'] = 'learning_stopped'
                    report['learning_error'] = f'{type(exc).__name__}: {exc}'
        report = json.loads(json.dumps(report))
        self.state['tasks'][key] = report
        self._save()
        return report

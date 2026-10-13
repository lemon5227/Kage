"""Frozen, one-attempt G2 baseline. Local student only; no learning or teacher path."""
import argparse
from dataclasses import asdict
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.model_broker import ModelBroker
from core.evolution.agent_provider import KageChainProvider
from core.evolution.artifacts import atomic_json
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.bundle import RecoveryPolicy
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.promotion import Promoter
from core.evolution.recovery_loop import classify_failure, _runtime_fault
from core.evolution.sandbox import DockerSkillRunner
from core.evolution.skills import SkillCatalog
from scripts.kage_recover import FiveStepLoop
from scripts.experiments.task_suite import RecordedLocalProvider
from scripts.experiments.native_model_pilot import LocalService

PROTOCOL = {'version': 1, 'max_tasks': 2, 'max_requests_total': 12,
            'max_requests_per_task': 6, 'max_steps': 5, 'max_tool_actions': 12,
            'timeout_s': 150, 'teacher_calls': 0, 'max_candidates': 0, 'attempts_per_task': 1}
SOURCE_FILES = (
    'scripts/experiments/recovery_baseline.py', 'scripts/experiments/task_suite.py',
    'scripts/experiments/native_model_pilot.py', 'scripts/kage_recover.py',
    'core/evolution/agent_provider.py', 'core/evolution/runner.py',
    'core/evolution/promotion.py', 'core/evolution/recovery_loop.py',
    'core/evolution/budget.py', 'core/evolution/journal.py', 'core/evolution/sandbox.py',
    'core/evolution/skills.py', 'core/evolution/bundle.py', 'core/evolution/mutator.py',
    'core/evolution/artifacts.py', 'core/evolution/contracts.py', 'core/agentic_loop.py',
    'core/model_broker.py', 'core/model_provider.py', 'core/prompt_builder.py',
    'core/tool_executor.py', 'core/tool_registry.py', 'tests/test_recovery_baseline_cli.py',
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _source_identity(suite_path):
    """Require committed execution sources and task input before touching services."""
    try:
        names = [*SOURCE_FILES, str(suite_path.relative_to(ROOT))]
    except ValueError as exc:
        raise ValueError('suite must be committed in this checkout') from exc
    tracked = set(subprocess.check_output(['git', 'ls-files', '--', *names], cwd=ROOT, text=True).splitlines())
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', *names], cwd=ROOT, text=True)
    if tracked != set(names) or dirty:
        raise ValueError('commit execution source, focused tests and suite before baseline')
    return {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'hashes': {name: _sha(ROOT / name) for name in names}}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f'invalid baseline JSON: {path}') from exc


def _inputs(config_path):
    cfg = _read_json(config_path)
    if not isinstance(cfg, dict) or set(cfg) != {'root', 'candidate_record', 'suite', 'student_settings'}:
        raise ValueError('baseline requires only root, candidate_record, suite, student_settings')
    def path(value):
        if not isinstance(value, str) or not value:
            raise ValueError('nonempty public path required')
        return (config_path.parent / Path(value).expanduser()).resolve()
    root, candidate_path, suite_path = map(path, (cfg['root'], cfg['candidate_record'], cfg['suite']))
    student = cfg['student_settings']
    if not isinstance(student, dict) or set(student) != {'model'}:
        raise ValueError('public local student mapping required')
    model = student['model']
    if not isinstance(model, dict) or set(model) - {'local_runtime', 'hybrid', 'broker'}:
        raise ValueError('local-only student required')
    runtime = model.get('local_runtime', {})
    if not isinstance(runtime, dict):
        raise ValueError('public local runtime mapping required')
    if (model.get('hybrid') != {'enabled': False} or
        not isinstance(model.get('broker', {}), dict) or
        any(value != 'local' for value in model.get('broker', {}).values()) or
        set(runtime) != {'host', 'port', 'model_name', 'timeout_sec'} or
        runtime['host'] != '127.0.0.1' or runtime['port'] != 18082 or
        isinstance(runtime['port'], bool) or runtime['model_name'] != 'agents-a1-4b' or
        isinstance(runtime['timeout_sec'], bool) or not isinstance(runtime['timeout_sec'], int) or
        not 1 <= runtime['timeout_sec'] <= 120):
        raise ValueError('fixed loopback local-only agents-a1-4b service required')
    local = {'model': {'local_runtime': runtime, 'hybrid': {'enabled': False}}}
    suite = _read_json(suite_path)
    if not isinstance(suite, dict):
        raise ValueError('public task suite mapping required')
    tasks = suite.get('tasks', [])
    if (suite.get('protocol') != PROTOCOL or not isinstance(tasks, list) or not 1 <= len(tasks) <= 2 or
        any(not isinstance(t, dict) or not isinstance(t.get('task_id'), str) or not t['task_id'] or
            t.get('split') != 'dev' for t in tasks) or len({t['task_id'] for t in tasks}) != len(tasks)):
        raise ValueError('fixed protocol requires one or two unique explicit dev tasks')
    record = _read_json(candidate_path)
    raw = record.get('candidate')
    if not isinstance(raw, dict):
        raise ValueError('G1 active candidate record required')
    candidate = Candidate(**{**raw, 'parent_ids': tuple(raw['parent_ids']), 'bundle_path': str(path(raw['bundle_path']))})
    if candidate.target != 'recovery' or bundle_digest(Path(candidate.bundle_path)) != candidate.digest:
        raise ValueError('immutable G1 recovery candidate required')
    source = _source_identity(suite_path)
    # Revision is retained as provenance, but unrelated future commits do not alter protocol.
    protocol = {'limits': PROTOCOL, 'root': str(root), 'candidate': asdict(candidate),
                'candidate_record_path': str(candidate_path), 'candidate_record_sha256': _sha(candidate_path),
                'candidate_source_sha256': RecoveryPolicy.from_bundle(candidate.bundle_path).digest,
                'suite_path': str(suite_path), 'suite_sha256': _sha(suite_path), 'tasks': tasks,
                'student_settings': local, 'source_hashes': source['hashes'],
                'run_namespace': hashlib.sha256(str(root).encode()).hexdigest()[:12],
                'step_isolation': 'fork', 'kernel_max_steps': 1,
                'max_input_tokens_total': 1_000_000, 'max_output_tokens_total': 24_000}
    return root, candidate, tasks, local, json.loads(json.dumps(protocol)), source


def _skill_calls(result):
    if not result.trace_path:
        return []
    rows = [json.loads(line) for line in Path(result.trace_path).read_text().splitlines() if line.strip()]
    return [{'step': row.get('step'), 'actor': row.get('observation', {}).get('actor',
                    row['action'].get('actor', 'student')),
             'action': row['action'], 'observation': row.get('observation', {})}
            for row in rows if isinstance(row.get('action'), dict) and row['action'].get('name') == 'skill_call']


def run_baseline(config_path):
    config_path = Path(config_path).expanduser().resolve()
    root, candidate, tasks, local, protocol, source = _inputs(config_path)
    root.mkdir(parents=True, exist_ok=True)
    # Advisory lock is held across the complete run; another worker cannot reserve an attempt.
    with (root / 'baseline.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('baseline already running in this root') from exc
        protocol_path, state_path, report_path = root / 'protocol.json', root / 'baseline-state.json', root / 'report.json'
        if protocol_path.exists() and _read_json(protocol_path) != protocol:
            raise ValueError('persistent baseline protocol changed')
        if state_path.exists():
            state = _read_json(state_path)
            if state.get('status') == 'complete' and report_path.is_file():
                return _read_json(report_path)
            raise RuntimeError('unresolved or interrupted baseline; attempts never replay')
        if protocol_path.exists():
            raise RuntimeError('unresolved baseline initialization; never replay')
        if any(p.name != 'baseline.lock' for p in root.iterdir()):
            raise ValueError('fresh independent baseline root required')
        atomic_json(protocol_path, protocol)
        state = {'status': 'running', 'attempts': {}}
        atomic_json(state_path, state)
        report = {'protocol': protocol, 'runs': [], 'can_learn': False,
                  'teacher_calls': 0, 'candidates_created': 0, 'stop_reason': 'baseline_complete'}
        budget = BudgetTracker(BudgetConfig(max_api_calls=12, max_input_tokens_total=1_000_000,
            max_output_tokens_total=24_000, input_cost_per_million=0, output_cost_per_million=0), root / 'local-budget.sqlite')
        try:
            docker = DockerSkillRunner(timeout_s=10)
            broker = ModelBroker(local)
            runtime = local['model']['local_runtime']
            catalog = SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=docker)
            report['skill_digests'] = catalog.digests
            def provider_factory(parent):
                policy = RecoveryPolicy.from_bundle(Path(parent.bundle_path), runner=docker, skill_catalog=catalog)
                model = RecordedLocalProvider(root / f'student-{parent.digest[:16]}.jsonl', api_key='local',
                    model_name=runtime['model_name'], base_url=f"http://127.0.0.1:{runtime['port']}/v1",
                    timeout_sec=runtime['timeout_sec'])
                return KageChainProvider(model, provider_mode='local', model_label=broker.background_provider.model_name,
                    max_model_calls=6, max_tool_actions=12, agentic_loop_cls=FiveStepLoop,
                    skill_catalog=catalog, recovery_policy=policy, skill_context_mode='search')
            # Bundle loading is a preflight, not a model request.
            provider_factory(candidate)
            promoter = Promoter(Journal(root / 'journal.sqlite'), budget, provider_factory, root,
                timeout_s=150, step_isolation='fork', kernel_max_steps=1, run_namespace=protocol['run_namespace'])
            with LocalService(runtime['port'], root) as service:
                frozen = {'protocol': protocol, 'git_revision': source['revision'],
                          'runtime': service.runtime, 'docker_image_id': docker.image_id,
                          'skill_digests': catalog.digests}
                atomic_json(root / 'freeze.json', frozen)
                for task in tasks:
                    state['attempts'][task['task_id']] = {'status': 'reserved'}
                    atomic_json(state_path, state)  # Durable before evaluate or any side effects.
                    result = promoter.evaluate(candidate, task)
                    kind = 'infrastructure' if _runtime_fault(result) else classify_failure(result)
                    row = {'task_id': task['task_id'], 'family': task.get('family'), 'result': asdict(result),
                           'failure_kind': kind, 'skill_calls': _skill_calls(result)}
                    report['runs'].append(row)
                    state['attempts'][task['task_id']] = {'status': 'finished', 'run_id': result.run_id}
                    atomic_json(root / 'results.json', report['runs'])
                    atomic_json(state_path, state)
                    if kind not in {'capability', 'none'}:
                        report['stop_reason'] = 'resource_or_infrastructure'
                        break
            source_rows = [row for row in report['runs'] if row['family'] == 'read_preserve']
            old_rows = [row for row in report['runs'] if row['family'] == 'code_repair']
            report['can_learn'] = (len(source_rows) == len(old_rows) == 1 and
                source_rows[0]['failure_kind'] == 'capability' and bool(source_rows[0]['skill_calls']) and
                old_rows[0]['failure_kind'] == 'none' and old_rows[0]['result']['score'] == 1 and
                any(call['observation'].get('success') is True and
                    call['observation'].get('outcome', 'ok') == 'ok' and
                    call['action'].get('arguments', {}).get('skill_id') in catalog.digests and
                    call['action']['arguments'].get('digest') == catalog.digests[call['action']['arguments']['skill_id']]
                    for call in old_rows[0]['skill_calls']))
            if not report['can_learn'] and report['stop_reason'] == 'baseline_complete':
                report['stop_reason'] = 'no_verified_learning_gap'
        except Exception as exc:
            report['stop_reason'] = 'infrastructure'
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        except BaseException:
            report['stop_reason'] = 'interrupted'
            state['status'] = 'interrupted'
            atomic_json(state_path, state)
            raise
        finally:
            budget.can_reserve(1, 1)  # Refresh persisted fork-worker accounting.
            report['budget'] = budget.to_dict()
            cleanup = root / 'service-cleanup.json'
            report['service_cleanup'] = _read_json(cleanup) if cleanup.exists() else {'service_not_started': True}
            atomic_json(report_path, report)
        state['status'] = 'complete'
        atomic_json(state_path, state)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_baseline(args.config)
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == '__main__':
    main()

"""Six predeclared development runs: clean cloud, compact-v1 versus explicit checked."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.computer_use.experiment import BrowserCloudProvider, BROWSER_SOUL
from core.computer_use.task_environment import atomic_json
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from scripts.experiments.browser_transfer import ReservedTeacher
from scripts.experiments.task_suite import RecordedLocalProvider


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def development_tasks():
    source = json.loads((ROOT/'eval/computer-use/browser-learning-v2.json').read_text())
    original = next(t for t in source['tasks'] if t['task_id'] == 'preferences_dev')
    tasks = []
    for suffix, initial, expected in [
        ('original', [False, True, False], [True, False, False]),
        ('satisfied', [True, False, False], [True, False, False]),
        ('reverse', [True, False, True], [False, True, False]),
    ]:
        task = json.loads(json.dumps(original))
        task['task_id'] = 'preferences_state_dev_' + suffix
        for field, value in zip(task['fixture']['fields'], initial): field['initial'] = value
        task['scoring_criteria']['expected']['record'] = dict(zip(('email', 'sms', 'weekly'), expected))
        if suffix == 'reverse':
            task['instruction'] = 'Disable Email notifications, enable SMS notifications, and disable Weekly digest. Save and confirm the saved settings.'
        tasks.append(task)
    return tasks


def summarize(rows):
    arms = {}
    for arm in ('compact-v1', 'compact-v2'):
        group = [r for r in rows if r['arm'] == arm]
        calls = [call for r in group for call in r.get('chain', {}).get('call_usage', [])]
        arms[arm] = {
            'expected_runs': 3, 'recorded_runs': len(group), 'passed': sum(r['status'] == 'passed' for r in group),
            'model_calls': len(calls), 'unknown_usage_calls': sum(not all(k in c for k in ('input_tokens', 'output_tokens')) for c in calls),
            'reported_tokens': {k: sum(c.get(k, 0) for c in calls) for k in ('input_tokens', 'output_tokens')},
            'seconds': round(sum(r['seconds'] for r in group), 3),
            'never_saved': sum(r['check'].get('posts') == 0 for r in group),
            'saved_wrong': sum(r['check'].get('posts', 0) > 0 and r['status'] != 'passed' for r in group),
        }
    return {'protocol': 'c21-r1-state-dev-v1', 'complete': len(rows) == 6, 'arms': arms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    cloud = json.loads(args.cloud_config.read_text())['model']['cloud_api']
    if cloud.get('model_name') != 'deepseek-flash' or cloud.get('base_url', '').rstrip('/') != 'https://api.deepseek.com' or not cloud.get('api_key'):
        parser.error('requires configured official DeepSeek Flash')
    tasks = development_tasks()
    sources = ['core/computer_use/'+s for s in ('browser.py', 'experiment.py', 'context_pack.py', 'skills.py', 'task_environment.py')]
    sources += ['core/'+s for s in ('model_provider.py', 'agentic_loop.py', 'prompt_builder.py', 'tool_executor.py', 'tool_registry.py')]
    sources += ['core/evolution/'+s for s in ('agent_provider.py', 'runner.py', 'budget.py')]
    sources += ['scripts/experiments/'+s for s in ('browser_state_diagnosis.py', 'browser_transfer.py', 'task_suite.py')]
    config = {'protocol': 'c21-r1-state-dev-v1', 'tasks': tasks, 'expected_runs': 6,
        'arms': ['compact-v1', 'compact-v2'], 'repeats': 1, 'split': 'dev-only',
        'executor': 'cloud_direct', 'model': cloud['model_name'], 'endpoint': cloud['base_url'],
        'thinking': False, 'temperature': 0, 'max_calls_per_run': 6, 'max_loop_steps': 5,
        'max_primitives': 16, 'timeout_s': 480, 'request_timeout_s': 60,
        'max_request_input_bytes': 12000, 'max_output_tokens': 1024, 'context_pack': True,
        'external_completion': True, 'assumed_rates_per_million': {'input': .3, 'output': 1.2},
        'max_assumed_cost_usd': .20, 'conservative_cost_ceiling_usd': .1738368,
        'order': 'task/alternating-arm-first', 'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_hashes': {s: sha(ROOT/s) for s in sources}, 'soul_sha256': hashlib.sha256(BROWSER_SOUL.encode()).hexdigest(),
        'python': platform.python_version(), 'playwright': importlib.metadata.version('playwright')}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config_path = args.output_dir/'config.json'
    if config_path.exists():
        if json.loads(config_path.read_text()) != config: parser.error('resume configuration changed')
    else: atomic_json(config_path, config)  # Freeze before any paid request.
    cloud_budget = BudgetConfig(max_api_calls=36, max_input_tokens_total=432000, max_output_tokens_total=36864,
        max_cost_usd=.20, input_cost_per_million=.3, output_cost_per_million=1.2)
    budget = BudgetTracker(BudgetConfig(max_api_calls=36, max_input_tokens_total=432000, max_output_tokens_total=36864,
        input_cost_per_million=0, output_cost_per_million=0), args.output_dir/'chain-budget.sqlite')
    journal = Journal(args.output_dir/'journal.sqlite')
    candidate = Candidate('state_diagnosis', (), 'workflow', str(ROOT), 'no-generated-candidate')
    path = args.output_dir/'results.json'
    rows = json.loads(path.read_text()) if path.exists() else []
    expected = {t['task_id']+'--'+a for t in tasks for a in config['arms']}
    keys = [r['key'] for r in rows]
    if len(set(keys)) != len(keys) or set(keys)-expected: parser.error('unexpected or duplicate result keys')
    for index, task in enumerate(tasks):
        for arm in config['arms'][::1 if index % 2 == 0 else -1]:
            key = task['task_id']+'--'+arm
            if key in keys: continue  # Terminal failures remain in the denominator.
            remote = RecordedLocalProvider(args.output_dir/(key+'-cloud.jsonl'), api_key=cloud['api_key'],
                model_name=cloud['model_name'], base_url=cloud['base_url'], timeout_sec=60, thinking=False, output_limit=1024)
            model = ReservedTeacher(remote, cloud_budget, args.output_dir/'cloud-budget.sqlite', key)
            provider = BrowserCloudProvider(model, task, model_label=cloud['model_name'], provider_mode='cloud',
                max_model_calls=6, external_completion=True, observation_format=arm)
            runner = EvolutionRunner(journal, budget, args.output_dir/'runs', provider, step_isolation='fork')
            start = time.monotonic()
            result = runner.run(candidate, task, RunSpec(key, candidate.candidate_id, task['task_id'], max_steps=1, timeout_s=480))
            workspace = Path(result.final_state_path)
            check_path = workspace/'browser-check.json'
            check = json.loads(check_path.read_text()) if check_path.exists() else {}
            chain = (result.metadata.get('chain') or [{}])[-1]
            names = ('actor-tools.jsonl', 'browser.jsonl', 'browser-outcome.json', 'browser-check.json', 'initial-observation.json', 'loop-result.json', 'cloud-context-pack.jsonl', 'final.png')
            row = {**asdict(result), 'key': key, 'arm': arm, 'task_id': task['task_id'],
                'seconds': round(time.monotonic()-start, 3), 'check': check, 'chain': chain,
                'evidence_hashes': {name: sha(workspace/name) for name in names if (workspace/name).exists()}}
            rows.append(row); keys.append(key); atomic_json(path, rows)
            report = summarize(rows)
            report['cloud_assumed_ledger'] = BudgetTracker(cloud_budget, args.output_dir/'cloud-budget.sqlite').to_dict()
            atomic_json(args.output_dir/'report.json', report)
            print(json.dumps({k: row[k] for k in ('key', 'status', 'score', 'seconds')}, ensure_ascii=False), flush=True)
    print(json.dumps(summarize(rows), ensure_ascii=False), flush=True)


if __name__ == '__main__': main()

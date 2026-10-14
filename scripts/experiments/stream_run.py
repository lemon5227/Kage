"""Kage-Stream vertical slice on the Mac: one family + negatives, learning between tasks.

Run (Mac, repository root, llama-server for Agents-A1-4B on --port, Docker image kage-evolution:local):

  python scripts/experiments/stream_run.py --arm A0 --root artifacts/stream-slice/A0 --plan-only   # freeze & inspect
  python scripts/experiments/stream_run.py --arm A0 --root artifacts/stream-slice/A0
  python scripts/experiments/stream_run.py --arm A4 --root artifacts/stream-slice/A4 \
      --teacher-cache artifacts/stream-slice/teacher-cache
  python scripts/experiments/stream_run.py --arm A5 --root artifacts/stream-slice/A5 \
      --teacher-cache artifacts/stream-slice/teacher-cache

The teacher cache is shared on purpose: each task is demonstrated once from its clean
state and reused by every arm. All paid calls go through the global $1 ledger.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import Mutator, bundle_digest
from core.evolution.playbook import Playbook, parse_lessons
from core.evolution.stream import ARMS, MemoryStore, StreamLearner, TeacherCache, chain_runner
from core.evolution.stream_tasks import manifest
from core.evolution.teacher_budget import global_teacher_budget, ledger_path, remaining_usd

TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json').expanduser()
# AgenticLoop's companion default caps each tool turn at 300 tokens, which truncated every
# student write_file before it was emitted (void A0 run 2026-10-14). Matches llama-server -n.
STUDENT_OUTPUT_TOKENS = 1024
# Teacher/optimizer request cap. 12000 bytes blocked format repairs, which resend the previous
# reply (E-0, 2026-10-14); 24000 bytes is about 6k input tokens, ~US$0.002 at the ledger price.
TEACHER_INPUT_BYTES = 24000
SKILL_FEEDBACK = ('The local student failed this task; the teacher demonstration below passed the external check. '
                  'Extract ONE reusable skill for this whole task family, not for this instance: take the target file path '
                  'and function name as parameters, implement the general procedure, and do not hardcode example names, '
                  'values or answers. Describe in the description exactly when the skill applies and when it does not.')
# W2-5 (E-0 diagnosis, 2026-10-14): skills were too narrow (one grouping field only) and one 6 KB
# reply was malformed JSON whose repair then exceeded the 12000-byte request cap. Same text for all arms.
SKILL_FEEDBACK += (' Instances of this family vary (for example which field to group or count by, optional filters); '
                   'expose every such variation stated in the instruction as a parameter instead of fixing one. '
                   'Start the description with "Use this when". Keep code compact (under 60 lines, no docstrings) '
                   'so the JSON reply stays small and valid.')


def experiment_spend(cache_dir: Path, remaining: float) -> float:
    """US$ spent from the global ledger since this experiment's first paid run.

    The baseline lives next to the shared teacher cache, so every arm of one experiment
    draws from the same allocation (task book §4) and a new --root cannot reset it.
    """
    base = cache_dir.parent / 'ledger-baseline.json'
    if not base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(json.dumps({'remaining_usd_at_start': remaining}))
    return max(0.0, json.loads(base.read_text())['remaining_usd_at_start'] - remaining)


HELP_POLICY = ROOT / 'core/evolvable/recovery_help.py'


def help_bundle(path: Path) -> Path:
    """Recovery bundle holding the W3-2 request_help policy (same manifest shape as G1 bundles)."""
    code = HELP_POLICY.read_text()
    path.mkdir(parents=True, exist_ok=True)
    (path / 'recovery.py').write_text(code)
    (path / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': [], 'modules': {'recovery': {
        'entrypoint': 'recovery.py:recover', 'digest': hashlib.sha256(code.encode()).hexdigest()}}}))
    return path


def _spend_row(root: Path, when: str, task: dict, remaining: float) -> None:
    """Ledger snapshots around each stream task: per-arm cloud spend for stream_report."""
    with (root / 'spend.jsonl').open('a') as out:
        out.write(json.dumps({'task_id': task['task_id'], 'when': when, 'ledger_remaining_usd': remaining}) + '\n')


def plan(args):
    stream = [('read_preserve' if i % 5 == 4 else 'log_aggregation', 1000 + i) for i in range(args.stream)]
    evals = [('log_aggregation', 9000 + i) for i in range(args.eval_capability)] + \
            [('read_preserve', 9500 + i) for i in range(args.eval_negative)]
    checkpoints = sorted({0, args.stream // 2, args.stream})
    return stream, evals, checkpoints


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--arm', choices=sorted(ARMS), required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--teacher-cache', type=Path, default=ROOT / 'artifacts/stream-slice/teacher-cache')
    p.add_argument('--stream', type=int, default=20)
    p.add_argument('--eval-capability', type=int, default=8)
    p.add_argument('--eval-negative', type=int, default=4)
    p.add_argument('--port', type=int, default=18082)
    p.add_argument('--teacher-config', type=Path, default=TEACHER_CONFIG)
    p.add_argument('--experiment-cap-usd', type=float, default=0.10,
                   help='stop before the next stream task once this experiment has spent this much (all arms)')
    p.add_argument('--playbook', action='store_true', help='W2-6: lessons from skill proposals join the student prompt')
    p.add_argument('--in-task-help', action='store_true',
                   help='W3-2: student runs with the request_help recovery policy (helping arms only)')
    p.add_argument('--stream-manifest', type=Path, help='frozen stream manifest (eval/stream_v1/stream-seedN.json)')
    p.add_argument('--eval-manifest', type=Path, help='frozen eval manifest (eval/stream_v1/eval.json)')
    p.add_argument('--checkpoints', help='comma-separated stream indexes for evaluation (default 0/middle/end)')
    p.add_argument('--eval-only', metavar='LABEL',
                   help='skip the stream; evaluate the bootstrap state once under LABEL (non-learning arms, shared cp0)')
    p.add_argument('--plan-only', action='store_true', help='write config.json with frozen manifests and exit')
    p.add_argument('--skill-runner', choices=['docker', 'process'], default='docker',
                   help='process: run skills in a subprocess (hosts without Docker, e.g. a disposable Kaggle VM)')
    p.add_argument('--no-manage-server', action='store_true', help='use an already running llama-server instead of the owned one')
    args = p.parse_args()

    if bool(args.stream_manifest) != bool(args.eval_manifest):
        p.error('give both --stream-manifest and --eval-manifest, or neither')
    if args.stream_manifest:
        from stream_freeze import load as load_frozen
        try:
            stream_m, eval_m = load_frozen(args.stream_manifest), load_frozen(args.eval_manifest)
        except ValueError as exc:
            p.error(str(exc))
        n = len(stream_m['tasks'])
        checkpoints = sorted({0, n // 2, n})
    else:
        stream, evals, checkpoints = plan(args)
        stream_m, eval_m = manifest(stream), manifest(evals)
    if args.checkpoints:
        checkpoints = sorted({int(x) for x in args.checkpoints.split(',')})
        if not checkpoints or checkpoints[0] < 0 or checkpoints[-1] > len(stream_m['tasks']):
            p.error('checkpoints must lie within the stream length')
    config = {'arm': args.arm, 'arm_definition': ARMS[args.arm], 'stream_sha256': stream_m['sha256'],
              'eval_sha256': eval_m['sha256'], 'stream_tasks': len(stream_m['tasks']), 'eval_tasks': len(eval_m['tasks']),
              'checkpoints': checkpoints, 'student': {'model': 'agents-a1-4b', 'port': args.port, 'max_model_calls': 6,
              'max_steps': 5, 'max_tool_actions': 12, 'timeout_s': 150, 'skill_context_mode': 'preview',
              'output_tokens': STUDENT_OUTPUT_TOKENS},
              'teacher_ledger': str(ledger_path()), 'teacher_cap_usd': 1.0, 'teacher_input_bytes': TEACHER_INPUT_BYTES}
    if ARMS[args.arm]['help'] != 'never':
        config['experiment_cap_usd'] = args.experiment_cap_usd
    if args.eval_only:
        if ARMS[args.arm]['learn'] and args.eval_only != 'cp0':
            p.error('--eval-only on a learning arm is only meaningful for cp0 (empty library)')
        config['eval_only'] = args.eval_only
    if args.skill_runner != 'docker':
        config['skill_runner'] = args.skill_runner
    if args.stream_manifest:
        config['stream_manifest'], config['eval_manifest'] = str(args.stream_manifest), str(args.eval_manifest)
    if args.playbook:
        if ARMS[args.arm]['learn'] is not True:
            p.error('--playbook needs a skill-learning arm (A4/A5)')
        config['playbook'] = True
    if args.in_task_help:
        if ARMS[args.arm]['help'] == 'never':
            p.error('--in-task-help needs an arm that can receive help')
        config['in_task_help'] = hashlib.sha256(HELP_POLICY.read_bytes()).hexdigest()
    args.root.mkdir(parents=True, exist_ok=True)
    cfg_path = args.root / 'config.json'
    if cfg_path.exists() and json.loads(cfg_path.read_text()) != config:
        p.error(f'{cfg_path} exists with a different frozen config; use a new --root')
    cfg_path.write_text(json.dumps(config, indent=2))
    if args.plan_only:
        print(json.dumps(config, indent=2))
        return

    import contextlib
    if args.no_manage_server:
        service = contextlib.nullcontext()
    else:
        from local_service import LocalService   # starts llama-server only if absent, stops only its own
        service = LocalService(args.port, args.root)
    with service:
        run(args, config, stream_m, eval_m, checkpoints)


def run(args, config, stream_m, eval_m, checkpoints):
    from core.evolution.sandbox import DockerSkillRunner, ProcessSkillRunner
    from task_suite import RecordedLocalProvider
    docker = DockerSkillRunner(timeout_s=10) if args.skill_runner == 'docker' else ProcessSkillRunner(timeout_s=10)
    journal = Journal(args.root / 'journal.sqlite')
    local_budget = BudgetTracker(BudgetConfig(max_api_calls=100_000, max_input_tokens_total=10**9,
        max_output_tokens_total=10**8, input_cost_per_million=0, output_cost_per_million=0), args.root / 'local-budget.sqlite')
    boot_dir = args.root / 'bootstrap'
    boot_dir.mkdir(exist_ok=True)
    (boot_dir / 'manifest.json').write_text('{"version":1,"skills":[]}')
    bootstrap = Candidate('no-skills', (), 'skill', str(boot_dir.resolve()), bundle_digest(boot_dir))
    (args.root / 'model-traces').mkdir(exist_ok=True)

    def student_model(run_id):
        return RecordedLocalProvider(args.root / 'model-traces' / f'{run_id}.jsonl', api_key='local',
            model_name='agents-a1-4b', base_url=f'http://127.0.0.1:{args.port}/v1', timeout_sec=120)
    learn = ARMS[args.arm]['learn']
    memory = MemoryStore(args.root / 'memory.jsonl') if learn == 'memory' else None
    playbook = Playbook(args.root / 'playbook.json') if args.playbook else None
    recovery_bundle = help_bundle(args.root / 'recovery-help') if args.in_task_help else None
    run_student = chain_runner(journal, local_budget, args.root / 'workspaces', student_model, skill_runner=docker,
                               tool_max_tokens=STUDENT_OUTPUT_TOKENS, memory=memory, playbook=playbook,
                               recovery_bundle=recovery_bundle,
                               mode='memory' if memory else 'retry' if args.arm == 'A1' else 'plain')

    teacher = proposer = None
    if ARMS[args.arm]['learn'] or ARMS[args.arm]['help'] != 'never':
        cloud = json.loads(args.teacher_config.read_text())['model']['cloud_api']
        print(json.dumps({'teacher_model': cloud.get('model_name'), 'ledger_remaining_usd': round(remaining_usd(global_teacher_budget()), 4)}))
        tjournal = Journal(args.teacher_cache.parent / 'teacher-journal.sqlite')
        args.teacher_cache.mkdir(parents=True, exist_ok=True)

        def teacher_model(run_id):
            return RecordedLocalProvider(args.teacher_cache / f'{run_id}-model.jsonl', api_key=cloud['api_key'],
                model_name=cloud['model_name'], base_url=cloud['base_url'], timeout_sec=60, thinking=False, output_limit=1024,
                input_byte_cap=TEACHER_INPUT_BYTES)
        teacher_run = chain_runner(tjournal, global_teacher_budget(), args.teacher_cache / 'workspaces', teacher_model, cloud=True)

        def solve(task):
            return teacher_run(bootstrap, task, f"teacher-{task['task_id']}")
        teacher = TeacherCache(args.teacher_cache / 'results', solve)

        def propose(parent, task, demo):
            optimizer = RecordedLocalProvider(args.root / 'optimizer-model.jsonl', api_key=cloud['api_key'],
                model_name=cloud['model_name'], base_url=cloud['base_url'], thinking=False, output_limit=3000,
                input_byte_cap=TEACHER_INPUT_BYTES)
            trace = [json.loads(l) for l in Path(demo.trace_path).read_text().splitlines() if l.strip()]
            feedback = {'task_id': task['task_id'], 'instruction': task['instruction'],
                        'failure_reason': SKILL_FEEDBACK, 'trace': trace}
            root = args.root / 'mutations' / task['task_id']
            try:
                return Mutator(optimizer, global_teacher_budget(), journal, root,
                               request_lessons=playbook is not None).propose(parent, feedback)
            finally:
                # Lessons are kept even when the skill is later rejected: the failure taught them.
                if playbook is not None and (root / 'lessons.json').exists():
                    lessons = parse_lessons(json.loads((root / 'lessons.json').read_text()))
                    playbook.add(lessons, source_task=task['task_id'], family=task['family'],
                                 trigger=task['instruction'])
                    playbook.save()
        proposer = propose if learn is True else None

    learner = StreamLearner(args.root, args.arm, bootstrap=bootstrap, run_student=run_student,
                            teacher=teacher, propose_skill=proposer, memory=memory)
    eval_tasks = eval_m['tasks']
    if args.eval_only:
        print(json.dumps(learner.evaluate(eval_tasks, args.eval_only)), flush=True)
        return
    capped = False
    for index, task in enumerate(stream_m['tasks'] + [None]):
        if index in checkpoints:            # evaluate() skips tasks already logged for this checkpoint
            summary = learner.evaluate(eval_tasks, f'cp{index}')
            print(json.dumps(summary), flush=True)
        if task is None or task['task_id'] in learner.done:
            continue
        if teacher and not capped:
            spent = experiment_spend(args.teacher_cache, remaining_usd(global_teacher_budget()))
            if spent >= args.experiment_cap_usd:
                capped = True     # remaining stream tasks are skipped; checkpoints still run
                print(json.dumps({'stopped': 'experiment_cap', 'spent_usd': round(spent, 4),
                                  'next_task': task['task_id']}), flush=True)
        if capped:
            continue
        start = time.monotonic()
        if teacher:
            _spend_row(args.root, 'before', task, remaining_usd(global_teacher_budget()))
        row = learner.step(task)
        if teacher:
            _spend_row(args.root, 'after', task, remaining_usd(global_teacher_budget()))
        print(json.dumps({k: row.get(k) for k in ('index', 'task_id', 'solved_by_student', 'helped', 'student_score',
              'teacher_score', 'learning', 'library_after')} | {'seconds': round(time.monotonic() - start, 1)},
              default=str), flush=True)
    print(json.dumps({'done': True, 'experiment_capped': capped, 'competence': learner.competence.summary(),
                      'ledger_remaining_usd': round(remaining_usd(global_teacher_budget()), 4) if teacher else None}), flush=True)


if __name__ == '__main__':
    main()

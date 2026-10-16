"""P4-L3 data: teacher demonstrations turned into student-format SFT examples.

  python scripts/experiments/distill_data.py collect --root artifacts/distill [--practice 30 --negative 10]
  python scripts/experiments/distill_data.py build   --root artifacts/distill

collect: teacher demonstrations (DeepSeek, global ledger) for
  - every task of the two frozen stream manifests (cached ones are reused, seeded from
    evidence/kaggle/v11-results.tar.gz), and
  - fresh variants from the *practice* split for the four stream-learned families and the
    three negative families.
  Held-out families (text_normalize, config_migrate) and eval/validation seeds are never used,
  so the eval set still measures transfer to unseen task types.

build: each passed demonstration is replayed, response by response, through the student's own
chain (A0 configuration: empty skill library, same prompt and tools). The request the student
would have sent at every step is recorded with the teacher's response as the target, so the
training data has exactly the format llama-server sees at inference. Replays that do not pass
the hidden checker in the student harness are dropped. No local model is started.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.evolution.budget import BudgetConfig, BudgetTracker          # noqa: E402
from core.evolution.contracts import Candidate                         # noqa: E402
from core.evolution.journal import Journal                             # noqa: E402
from core.evolution.mutator import bundle_digest                       # noqa: E402
from core.evolution.sandbox import ProcessSkillRunner                  # noqa: E402
from core.evolution.stream import TeacherCache, chain_runner, wrote_files  # noqa: E402
from core.evolution.stream_tasks import NEGATIVE_FAMILIES, SPLITS, make_task, split_of  # noqa: E402
from core.evolution.teacher_budget import global_teacher_budget, remaining_usd  # noqa: E402
from core.model_provider import ModelResponse, OpenAICompatibleProvider  # noqa: E402

LEARNED = ('subset_selection', 'interval_merge', 'log_aggregation', 'csv_transform')
HELD_OUT = ('text_normalize', 'config_migrate')
TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json').expanduser()
# Practice seeds used here start well past the ones A6 consumed (13000 + up to ~40 per family).
PRACTICE_OFFSET = 1000


def bootstrap(root: Path) -> Candidate:
    boot = root / 'bootstrap'
    boot.mkdir(parents=True, exist_ok=True)
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    return Candidate('no-skills', (), 'skill', str(boot.resolve()), bundle_digest(boot))


def task_list(practice: int, negative: int) -> list[dict]:
    tasks = []
    for name in ('stream-seed1.json', 'stream-seed2.json'):
        for t in json.loads((ROOT / 'eval/stream_v1' / name).read_text())['tasks']:
            if t['task_id'] not in {x['task_id'] for x in tasks}:
                tasks.append(t)
    start = SPLITS['practice'].start + PRACTICE_OFFSET
    for family in LEARNED:
        tasks += [make_task(family, start + i) for i in range(practice)]
    for family in sorted(NEGATIVE_FAMILIES):
        tasks += [make_task(family, start + i) for i in range(negative)]
    for t in tasks:
        seed = int(t['task_id'].rsplit('-', 1)[1])
        if t['family'] in HELD_OUT or split_of(seed) not in ('stream', 'practice'):
            raise ValueError(f"{t['task_id']} must not be used for training")
    return tasks


def seed_cache(cache: Path) -> None:
    if cache.exists():
        return
    stage = cache.parent / '.v11'
    stage.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ROOT / 'evidence/kaggle/v11-results.tar.gz') as tar:
        members = [m for m in tar.getmembers() if m.name.startswith('e1/teacher-cache/')]
        tar.extractall(stage, members=members, filter='data')
    shutil.move(str(stage / 'e1' / 'teacher-cache'), cache)
    shutil.rmtree(stage)
    for f in (cache / 'results').glob('*.json'):          # repoint traces from /kaggle/working to here
        r = json.loads(f.read_text())
        r['trace_path'] = str(r.get('trace_path', '')).replace('/kaggle/working/e1/teacher-cache', str(cache))
        f.write_text(json.dumps(r))


def collect(args) -> None:
    from task_suite import RecordedLocalProvider
    from stream_run import TEACHER_INPUT_BYTES
    root, cache = args.root, args.root / 'teacher-cache'
    seed_cache(cache)
    cloud = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']
    boot = bootstrap(root)

    def teacher_model(run_id):
        return RecordedLocalProvider(cache / f'{run_id}-model.jsonl', api_key=cloud['api_key'],
                                     model_name=cloud['model_name'], base_url=cloud['base_url'], timeout_sec=60,
                                     thinking=False, output_limit=1024, input_byte_cap=TEACHER_INPUT_BYTES)
    teacher_run = chain_runner(Journal(root / 'teacher-journal.sqlite'), global_teacher_budget(),
                               cache / 'workspaces', teacher_model, cloud=True)
    teacher = TeacherCache(cache / 'results', lambda task: teacher_run(boot, task, f"teacher-{task['task_id']}"))
    start = remaining_usd(global_teacher_budget())
    rows = []
    for i, task in enumerate(task_list(args.practice, args.negative)):
        if start - remaining_usd(global_teacher_budget()) >= args.cap_usd:
            print(json.dumps({'stopped': 'cap', 'at': task['task_id']}), flush=True)
            break
        demo = teacher.get(task)
        rows.append({'task_id': task['task_id'], 'family': task['family'], 'status': demo.status, 'score': demo.score})
        print(json.dumps(rows[-1]), flush=True)
    (root / 'collected.json').write_text(json.dumps(rows, indent=1))
    print(json.dumps({'demos': len(rows), 'passed': sum(r['score'] >= 1 for r in rows),
                      'spent_usd': round(start - remaining_usd(global_teacher_budget()), 4)}))


class ReplayProvider(OpenAICompatibleProvider):
    """Plays back recorded teacher responses; records the student-format request at each step."""

    def __init__(self, responses: list[dict], sink: Path):
        # The chain calls the model from its worker, so steps are recorded through a file.
        super().__init__(api_key='replay', model_name='replay', base_url='http://127.0.0.1:9')
        self.responses, self.sink = list(responses), Path(sink)

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        if not self.responses:
            return ModelResponse(text='Done.')
        r = self.responses.pop(0)
        with self.sink.open('a') as out:
            out.write(json.dumps({'messages': messages, 'tools': tools or [], 'response': r}, ensure_ascii=False) + '\n')
        return ModelResponse(text=r.get('text') or '', tool_calls=r.get('tool_calls') or [])


def _openai_args(arguments):
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except ValueError:
            return {'raw': arguments}
    return arguments or {}


def to_chat(messages: list[dict]) -> list[dict]:
    """Template-ready messages: tool-call arguments as objects (the chat template iterates them)."""
    out = []
    for m in messages:
        m = dict(m)
        if m.get('tool_calls'):
            m['tool_calls'] = [{'type': 'function', 'function': {
                'name': (c.get('function') or c)['name'],
                'arguments': _openai_args((c.get('function') or c).get('arguments'))}} for c in m['tool_calls']]
        out.append(m)
    return out


def build(args) -> None:
    root, cache = args.root, args.root / 'teacher-cache'
    seed_cache(cache)
    boot = bootstrap(root)
    budget = BudgetTracker(BudgetConfig(max_api_calls=10**6, max_input_tokens_total=10**10,
                                        max_output_tokens_total=10**9), root / 'replay-budget.sqlite')
    pending: dict[str, list] = {}

    def model_factory(run_id):
        return ReplayProvider(pending['responses'], pending['sink'])
    run = chain_runner(Journal(root / 'replay-journal.sqlite'), budget, root / 'replay-ws', model_factory,
                       skill_runner=ProcessSkillRunner(timeout_s=10), tool_max_tokens=1024)
    tasks = {t['task_id']: t for t in task_list(args.practice, args.negative)}
    examples, stats = [], {'demos': 0, 'teacher_passed': 0, 'replay_passed': 0, 'examples': 0}
    for f in sorted((cache / 'results').glob('*.json')):
        result = json.loads(f.read_text())
        task_id = result['run_id'].removeprefix('teacher-')
        if task_id not in tasks:
            continue
        stats['demos'] += 1
        if result.get('score', 0) < 1.0:
            continue
        stats['teacher_passed'] += 1
        trace = cache / f'teacher-{task_id}-model.jsonl'
        responses = [json.loads(l)['response'] for l in trace.read_text().splitlines() if l.strip()]
        sink = root / 'replay-steps' / f'{task_id}.jsonl'
        sink.parent.mkdir(exist_ok=True)
        sink.unlink(missing_ok=True)
        pending.update(responses=responses, sink=sink)
        replay = run(boot, tasks[task_id], f'replay-{task_id}')
        if replay.score < 1.0:
            continue
        stats['replay_passed'] += 1
        for step in (json.loads(l) for l in sink.read_text().splitlines() if l.strip()):
            r = step['response']
            target = {'role': 'assistant', 'content': r.get('text') or ''}
            if r.get('tool_calls'):
                target['tool_calls'] = r['tool_calls']
            examples.append({'task_id': task_id, 'family': tasks[task_id]['family'],
                             'negative': tasks[task_id].get('negative', False),
                             'writes': wrote_files(replay), 'tools': step['tools'],
                             'messages': to_chat(step['messages']), 'target': to_chat([target])[0]})
    stats['examples'] = len(examples)
    with (root / 'sft.jsonl').open('w') as out:
        for e in examples:
            out.write(json.dumps(e, ensure_ascii=False) + '\n')
    (root / 'sft-stats.json').write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('step', choices=['collect', 'build'])
    p.add_argument('--root', type=Path, default=ROOT / 'artifacts' / 'distill')
    p.add_argument('--practice', type=int, default=30, help='practice-split demos per stream-learned family')
    p.add_argument('--negative', type=int, default=10, help='practice-split demos per negative family')
    p.add_argument('--cap-usd', type=float, default=0.35)
    args = p.parse_args(argv)
    args.root.mkdir(parents=True, exist_ok=True)
    collect(args) if args.step == 'collect' else build(args)


if __name__ == '__main__':
    main()

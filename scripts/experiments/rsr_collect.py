"""R2: runbook-guided fresh execution turned into guidance-free SFT samples.

  python scripts/experiments/rsr_collect.py collect --root artifacts/rsr --port 18082 \
      --families subset_selection,interval_merge,log_aggregation,csv_transform \
      --seeds 8 --k 2 --temperature 0.6 --guidance demo \
      --memory a/memory.jsonl --memory b/memory.jsonl [--negatives 2]
  python scripts/experiments/rsr_collect.py build --root artifacts/rsr

collect: the frozen student runs fresh *practice*-split variants (13xxx) with a retrieved
demonstration and/or playbook lessons in context, k attempts per task at the given temperature.
No teacher and no cloud calls. Every attempt is logged; a crashed run stops the job and is never
recorded. Attempts already in attempts.jsonl are not rerun.

build: strict successes (score 1.0) only. Each recorded model call becomes one SFT row in the
same format as evidence/distill/sft.jsonl, with the guidance removed from the messages: the
prepended demonstration turns and the rendered lessons block are stripped exactly, then
leakage.guidance_free must hold. Targets are never screened: they legitimately contain this
task's values.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.evolution.agent_provider import KageChainProvider            # noqa: E402
from core.evolution.budget import BudgetConfig, BudgetTracker          # noqa: E402
from core.evolution.code_tasks import CODE_REPLAY_FAMILIES              # noqa: E402
from core.evolution.contracts import Candidate                         # noqa: E402
from core.evolution.journal import Journal                             # noqa: E402
from core.evolution.leakage import guidance_free                       # noqa: E402
from core.evolution.mutator import bundle_digest                       # noqa: E402
from core.evolution.playbook import Playbook                           # noqa: E402
from core.evolution.relevance import RELEVANCE_MIN, InstructionSpace   # noqa: E402
from core.evolution.stream import (MEMORY_TOTAL_CHARS, InfrastructureError, MemoryStore,  # noqa: E402
                                   chain_runner, wrote_files)
from core.evolution.stream_tasks import SPLITS, make_task, split_of    # noqa: E402
from distill_data import to_chat                                       # noqa: E402

COLLECT_FAMILIES = ('subset_selection', 'interval_merge', 'log_aggregation', 'csv_transform',
                    'web_invoice', 'web_prefs', 'web_catalog')
TRANSFER_FAMILIES = ('text_normalize', 'config_migrate', 'web_form')   # never trained
NEGATIVE_COLLECT = ('read_preserve', 'inspect_question', 'lookalike_readonly', 'web_lookup')
PRACTICE_START = SPLITS['practice'].start
STUDENT_OUTPUT_TOKENS = 1024        # same as stream_run.py (the companion default truncated writes)
MAX_STEPS = 5
MAX_TOOL_ACTIONS = 12


# ---------------------------------------------------------------- config and planning
def guidance_kinds(value: str) -> list[str]:
    # 'none' is the control: the same tasks and temperature without any guidance (v20 showed guided yields
    # far above A0's greedy evaluation; this separates the effect of guidance from that of sampling).
    return {'none': [], 'demo': ['demo'], 'lessons': ['lessons'], 'both': ['demo', 'lessons']}[value]


def practice_seeds(count: int) -> list[int]:
    """The first ``count`` practice-split seeds; refuse to run into validation/eval."""
    seeds = list(range(PRACTICE_START, PRACTICE_START + count))
    if count < 1 or any(split_of(seed) != 'practice' for seed in seeds):
        raise ValueError(f'seeds must stay inside the practice split ({PRACTICE_START}..16999)')
    return seeds


def practice_task(family: str, seed: int) -> dict:
    assert split_of(seed) == 'practice', f'{seed} is not a practice seed'
    return make_task(family, seed)


def validate_collect(parser, args) -> None:
    families = [name.strip() for name in args.families.split(',') if name.strip()]
    # R3f: the code-replay families are the frozen student's own unguided solutions (self-distillation), never guided.
    allowed = COLLECT_FAMILIES + (tuple(CODE_REPLAY_FAMILIES) if args.guidance == 'none' else ())
    refused = [name for name in families if name not in allowed]
    if not families or refused:
        parser.error(f'{", ".join(refused) or "no family"} cannot be collected; allowed: '
                     f'{", ".join(allowed)} (transfer families stay untrained: '
                     f'{", ".join(TRANSFER_FAMILIES)})')
    if args.seeds < 1 or args.k < 1 or args.negatives < 0:
        parser.error('--seeds and --k must be positive; --negatives must be >= 0')
    try:
        practice_seeds(args.seeds)
    except ValueError as exc:
        parser.error(str(exc))
    kinds = guidance_kinds(args.guidance)
    if 'demo' in kinds and not args.memory:
        parser.error('--guidance demo needs at least one --memory file')
    if 'lessons' in kinds and not args.playbook:
        parser.error('--guidance lessons needs at least one --playbook file')


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as out:
        out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')


# ---------------------------------------------------------------- guidance inputs
def prepare_guidance(root: Path, memory_files: list[str], playbook_files: list[str]) -> tuple[Path, Path, InstructionSpace]:
    """Merge the inputs into one memory store and playbook; observe all guidance instructions."""
    guidance = root / 'guidance'
    guidance.mkdir(parents=True, exist_ok=True)
    memory_path = guidance / 'memory.jsonl'
    lines = []
    for name in memory_files:
        lines += [line for line in Path(name).read_text().splitlines() if line.strip()]
    memory_path.write_text(''.join(line.rstrip('\n') + '\n' for line in lines))

    entries = []
    for name in playbook_files:
        entries += [dict(entry) for entry in Playbook(name).entries]
    for index, entry in enumerate(entries, 1):
        entry['id'] = f'L{index}'          # ids collide across source playbooks
    playbook_path = guidance / 'playbook.json'
    merged = Playbook(playbook_path)
    merged.entries = entries
    merged.save()

    space = InstructionSpace(guidance / 'space.json')
    for entry in MemoryStore(memory_path).entries():
        space.observe(entry['instruction'])
    for entry in entries:
        for trigger in entry.get('triggers') or []:
            space.observe(trigger)
    return memory_path, playbook_path, space


def memory_lookup(memory: MemoryStore, instruction: str) -> tuple[int | None, list[dict]]:
    """Index and rows of the demonstration MemoryStore.retrieve would return (None, [] if none)."""
    best = (0.0, None)
    for index, entry in enumerate(memory.entries()):
        score = memory.similarity(instruction, entry['instruction'])
        if score > best[0]:
            best = (score, index)
    if best[1] is None or best[0] < memory.min_jaccard:
        return None, []
    return best[1], memory.retrieve(instruction)


def _trimmed(rows: list[dict]) -> list[dict]:
    rows = list(rows)
    while rows and len(json.dumps(rows, ensure_ascii=False)) > MEMORY_TOTAL_CHARS:
        rows.pop(0)
    return rows


# ---------------------------------------------------------------- collect
def bootstrap(root: Path) -> Candidate:
    boot = root / 'bootstrap'
    boot.mkdir(parents=True, exist_ok=True)
    (boot / 'manifest.json').write_text('{"version":1,"skills":[]}')
    return Candidate('no-skills', (), 'skill', str(boot.resolve()), bundle_digest(boot))


def collect_tasks(args, model_factory, *, skill_runner=None) -> None:
    """Run the guided (and negative) attempts; ``model_factory(run_id)`` builds a tracing provider."""
    root = Path(args.root)
    kinds = guidance_kinds(args.guidance)
    memory_path, playbook_path, space = prepare_guidance(root, args.memory, args.playbook)
    memory = (MemoryStore(memory_path, min_jaccard=RELEVANCE_MIN, similarity=space.similarity)
              if 'demo' in kinds else None)
    playbook = Playbook(playbook_path) if 'lessons' in kinds else None
    traces = root / 'traces'
    traces.mkdir(parents=True, exist_ok=True)
    attempts, skipped = root / 'attempts.jsonl', root / 'skipped.jsonl'

    journal = Journal(root / 'journal.sqlite')
    budget = BudgetTracker(BudgetConfig(max_api_calls=10**6, max_input_tokens_total=10**10,
                                        max_output_tokens_total=10**9, input_cost_per_million=0,
                                        output_cost_per_million=0), root / 'local-budget.sqlite')
    common = dict(skill_runner=skill_runner, tool_max_tokens=STUDENT_OUTPUT_TOKENS,
                  max_steps=MAX_STEPS, max_tool_actions=MAX_TOOL_ACTIONS)
    guided = chain_runner(journal, budget, root / 'workspaces', model_factory,
                          memory=memory, playbook=playbook,
                          playbook_similarity=space.similarity if playbook is not None else None,
                          playbook_min=RELEVANCE_MIN, mode='memory' if memory is not None else 'plain',
                          **common)
    plain = chain_runner(journal, budget, root / 'workspaces', model_factory, **common)
    candidate = bootstrap(root)
    done = {(row['task_id'], int(row['attempt'])) for row in _jsonl(attempts)}
    already_skipped = {row['task_id'] for row in _jsonl(skipped)}

    def record(task: dict, attempt: int, run_id: str, result, guidance: list[str], *,
               demo_index=None, demo_instruction='', lesson_ids=()) -> None:
        _append(attempts, {'run_id': run_id, 'task_id': task['task_id'], 'family': task['family'],
                           'seed': int(task['task_id'].rsplit('-', 1)[1]), 'attempt': attempt,
                           'guidance': guidance, 'demo_index': demo_index,
                           'demo_instruction': demo_instruction, 'lesson_ids': list(lesson_ids),
                           'score': result.score, 'status': result.status,
                           'writes': wrote_files(result), 'negative': bool(task.get('negative')),
                           'trace': str(root / 'traces' / f'{run_id}.jsonl')})
        print(json.dumps({'task_id': task['task_id'], 'attempt': attempt, 'score': result.score,
                          'status': result.status, 'guidance': guidance}), flush=True)

    for family in [name.strip() for name in args.families.split(',') if name.strip()]:
        for seed in practice_seeds(args.seeds):
            task = practice_task(family, seed)
            space.observe(task['instruction'])
            demo_index, demo_rows = memory_lookup(memory, task['instruction']) if memory is not None else (None, [])
            lessons = (playbook.select(task['instruction'], similarity=space.similarity,
                                      min_score=RELEVANCE_MIN) if playbook is not None else [])
            used = (['demo'] if demo_rows else []) + (['lessons'] if lessons else [])
            if not used and kinds:
                if task['task_id'] not in already_skipped:
                    _append(skipped, {'task_id': task['task_id'], 'family': family, 'seed': seed,
                                      'reason': 'no_guidance'})
                    already_skipped.add(task['task_id'])
                    print(json.dumps({'task_id': task['task_id'], 'skipped': 'no_guidance'}), flush=True)
                continue
            demo_instruction = (MemoryStore(memory_path).entries()[demo_index]['instruction']
                                if demo_index is not None else '')
            lesson_ids = [entry['id'] for entry in lessons]
            for attempt in range(args.k):
                if (task['task_id'], attempt) in done:
                    continue
                run_id = f"rsr-{task['task_id']}-a{attempt}{args.run_suffix}"
                result = guided(candidate, task, run_id)
                if result.status == 'crashed':
                    raise InfrastructureError(f'{run_id} crashed (infrastructure); not recorded')
                record(task, attempt, run_id, result, used, demo_index=demo_index,
                       demo_instruction=demo_instruction, lesson_ids=lesson_ids)
                done.add((task['task_id'], attempt))

    for family in NEGATIVE_COLLECT:
        for seed in practice_seeds(args.negatives) if args.negatives else []:
            task = practice_task(family, seed)
            if (task['task_id'], 0) in done:
                continue
            run_id = f"rsr-{task['task_id']}-a0{args.run_suffix}"
            result = plain(candidate, task, run_id)
            if result.status == 'crashed':
                raise InfrastructureError(f'{run_id} crashed (infrastructure); not recorded')
            record(task, 0, run_id, result, [])
            done.add((task['task_id'], 0))


def collect(args, skill_runner) -> None:
    from task_suite import RecordedLocalProvider

    def model_factory(run_id):
        return RecordedLocalProvider(Path(args.root) / 'traces' / f'{run_id}.jsonl', api_key='local',
                                     model_name='agents-a1-4b', base_url=f'http://127.0.0.1:{args.port}/v1',
                                     timeout_sec=120, temperature=args.temperature)
    collect_tasks(args, model_factory, skill_runner=skill_runner)


# ---------------------------------------------------------------- build
def strip_guidance(messages: list[dict], demo_messages: list[dict], rendered: str) -> tuple[list[dict], bool]:
    """Remove the rendered lessons block and prepended demonstration turns; report exact removal.

    PromptBuilder trims history from the front, so only a suffix of the demonstration can remain;
    it stays contiguous. Returns (messages, lessons_found).
    """
    out = [dict(message) for message in messages]
    found = not rendered
    if rendered:
        marker = '\n' + rendered
        for message in out:
            content = str(message.get('content') or '')
            if message.get('role') == 'system' and marker in content:
                message['content'] = content.replace(marker, '', 1)
                found = True
    for start in range(len(demo_messages)):
        suffix = demo_messages[start:]
        for position in range(1, len(out) - len(suffix) + 1):
            if out[position:position + len(suffix)] == suffix:
                return out[:position] + out[position + len(suffix):], found
    return out, found


def _sample_key(messages: list[dict], target: dict) -> str:
    body = json.dumps([messages, target], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def _new_family() -> dict:
    return {'tasks': set(), 'attempts': 0, 'successes': 0, 'samples_kept': 0,
            'dropped': {'guidance_not_removed': 0, 'duplicate': 0, 'cap': 0, 'no_trace': 0}}


def build(args) -> dict:
    root = Path(args.root)
    attempts, skipped = _jsonl(root / 'attempts.jsonl'), _jsonl(root / 'skipped.jsonl')
    memory_path, playbook_path = root / 'guidance' / 'memory.jsonl', root / 'guidance' / 'playbook.json'
    memory_entries = MemoryStore(memory_path).entries() if memory_path.exists() else []
    playbook = Playbook(playbook_path)
    by_id = {entry['id']: entry for entry in playbook.entries}
    families = sorted({row['family'] for row in attempts} | {row['family'] for row in skipped})
    stats = {family: _new_family() for family in families}
    no_guidance = {}
    for row in skipped:
        no_guidance[row['family']] = no_guidance.get(row['family'], 0) + 1

    seen, samples = set(), []
    for attempt in sorted(attempts, key=lambda row: (row['family'], row['seed'], row['task_id'], row['attempt'])):
        family = attempt['family']
        state = stats.setdefault(family, _new_family())
        state['tasks'].add(attempt['task_id'])
        state['attempts'] += 1
        if float(attempt.get('score') or 0) < 1.0:
            continue
        state['successes'] += 1
        task = practice_task(family, int(attempt['seed']))
        demo_index = attempt.get('demo_index')
        demo_rows = (_trimmed(memory_entries[demo_index]['rows'])
                     if demo_index is not None and 0 <= demo_index < len(memory_entries) else [])
        demo_messages = KageChainProvider._history_messages(task, demo_rows) if demo_rows else []
        rendered = Playbook.render([by_id[i] for i in attempt.get('lesson_ids') or [] if i in by_id])
        trace = Path(attempt['trace'])
        if not trace.exists():
            state['dropped']['no_trace'] += 1
            continue
        for line in trace.read_text().splitlines():
            if not line.strip():
                continue
            step = json.loads(line)
            messages, removed = strip_guidance(step.get('messages') or [], demo_messages, rendered)
            guidance_texts = [rendered] + [str(m.get('content') or '') for m in demo_messages]
            if not removed or not guidance_free(messages, guidance_texts):
                state['dropped']['guidance_not_removed'] += 1
                continue
            response = step.get('response') or {}
            target = {'role': 'assistant', 'content': response.get('text') or ''}
            if response.get('tool_calls'):
                target['tool_calls'] = response['tool_calls']
            sample = {'task_id': attempt['task_id'], 'family': family,
                      'negative': bool(task.get('negative')), 'writes': bool(attempt.get('writes')),
                      'tools': (step.get('request') or {}).get('tools') or [],
                      'messages': to_chat(messages), 'target': to_chat([target])[0],
                      'source': 'rsr', 'attempt': int(attempt['attempt']),
                      'guidance': attempt.get('guidance') or []}
            key = _sample_key(sample['messages'], sample['target'])
            if key in seen:
                state['dropped']['duplicate'] += 1
                continue
            if sum(row['family'] == family for row in samples) >= args.cap:
                state['dropped']['cap'] += 1
                continue
            seen.add(key)
            samples.append(sample)
            state['samples_kept'] += 1

    def summary(state: dict) -> dict:
        attempts_n = state['attempts']
        return {'tasks': len(state['tasks']), 'attempts': attempts_n, 'successes': state['successes'],
                'yield': round(state['successes'] / attempts_n, 4) if attempts_n else 0.0,
                'samples_kept': state['samples_kept'], 'dropped': state['dropped']}

    report = {'families': {family: summary(state) for family, state in stats.items()},
              'no_guidance': no_guidance}
    totals = _new_family()
    for state in stats.values():
        totals['tasks'] |= state['tasks']
        totals['attempts'] += state['attempts']
        totals['successes'] += state['successes']
        totals['samples_kept'] += state['samples_kept']
        for reason, count in state['dropped'].items():
            totals['dropped'][reason] = totals['dropped'].get(reason, 0) + count
    report['totals'] = summary(totals)
    with (root / 'sft.jsonl').open('w') as out:
        for sample in samples:
            out.write(json.dumps(sample, ensure_ascii=False) + '\n')
    (root / 'stats.json').write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({**report['totals'], 'samples': len(samples)}, ensure_ascii=False))
    return report


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    steps = parser.add_subparsers(dest='step', required=True)
    c = steps.add_parser('collect', help='run guided student attempts from the practice split')
    c.add_argument('--root', type=Path, required=True)
    c.add_argument('--port', type=int, default=18082)
    c.add_argument('--families', required=True, help='comma-separated capability families')
    c.add_argument('--seeds', type=int, default=8, help='practice seeds per family, starting at 13000')
    c.add_argument('--k', type=int, default=4, help='attempts per task')
    c.add_argument('--temperature', type=float, default=0.6)
    c.add_argument('--memory', action='append', default=[], help='memory.jsonl to merge as demonstrations')
    c.add_argument('--playbook', action='append', default=[], help='playbook.json to merge as lessons')
    c.add_argument('--guidance', choices=['none', 'demo', 'lessons', 'both'], required=True)
    c.add_argument('--negatives', type=int, default=0, help='read-only tasks per negative family')
    c.add_argument('--skill-runner', choices=['docker', 'process'], default='docker')
    c.add_argument('--no-manage-server', action='store_true')
    b = steps.add_parser('build', help='strict successes -> guidance-free SFT rows')
    b.add_argument('--root', type=Path, required=True)
    b.add_argument('--cap', type=int, default=400, help='maximum samples kept per family')
    return parser


def main(argv=None) -> None:
    import contextlib
    parser = build_parser()
    args = parser.parse_args(argv)
    args.run_suffix = __import__('os').environ.get('KAGE_RUN_SUFFIX', '')
    if args.step == 'build':
        build(args)
        return
    validate_collect(parser, args)
    args.root.mkdir(parents=True, exist_ok=True)
    if args.no_manage_server:
        service = contextlib.nullcontext()
    else:
        from local_service import LocalService
        service = LocalService(args.port, args.root)
    if args.skill_runner == 'process':
        from core.evolution.sandbox import ProcessSkillRunner
        skill_runner = ProcessSkillRunner(timeout_s=10)
    else:
        from core.evolution.sandbox import DockerSkillRunner
        skill_runner = DockerSkillRunner(timeout_s=10)
    with service:
        collect(args, skill_runner)


if __name__ == '__main__':
    main()

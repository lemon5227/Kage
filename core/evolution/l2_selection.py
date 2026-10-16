"""A6 L2 step: the architect evolves the skill-selection policy (W4-3 wired into W4-5).

Per round:
  1. parent = the active select() module (the human-written relevance rule at first);
  2. validation = one fresh task per known cluster from the dedicated validation split
     (17000–18999; never stream, practice or eval instances), run with the parent policy;
  3. archive = parent source + per-task gate rows (similarity, verified_on, shown ids) +
     scores + failing traces, scrubbed of hidden scoring data;
  4. the architect proposes one module; only target skill_selection is wired here;
  5. the child runs the same tasks under the same budget; it becomes active only if no task
     regresses and at least one improves (architect.promote); every outcome is in lineage.jsonl.
A6-fixed skips this step and keeps the human-written rule.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.evolution.architect import promote, scrub, write_archive, write_module
from core.evolution.lineage import Lineage, Version
from core.evolution.relevance import FIXED_SELECT, skill_ids
from core.evolution.stream import _checked
from core.evolution.stream_tasks import SPLITS, make_task

VALIDATION_SEEDS_PER_ROUND = 10

BRIEF = (
    "Kage's student is a 4B local model. Before each task, a skill-selection policy decides which "
    "learned skills (at most 3) the student sees; with none, it runs exactly as the raw student. "
    "Showing an irrelevant skill can distract it; hiding a relevant one loses the learned procedure. "
    "Each validation task directory holds gate.json: for every skill its similarity to the instructions "
    "it was verified on, those instructions, and which ids the current policy showed; plus the score. "
    "Propose target skill_selection only: python `def select(instruction, skills) -> list` returning "
    "skill_ids, where skills rows are {skill_id, similarity, verified_on}."
)


def _digest(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def validation_tasks(learner, round_index: int) -> list[dict]:
    seeds = SPLITS['validation']
    seed = seeds.start + round_index * VALIDATION_SEEDS_PER_ROUND
    if seed not in seeds:
        raise ValueError('validation seed range exhausted')
    tasks = []
    for cluster in learner.clusters.clusters:
        generator = cluster['generators'][0] if cluster['generators'] else None
        if generator:
            tasks.append(make_task(generator, seed))
    return tasks


def selection_step(learner, *, label: str, round_index: int, architect, run_student=None) -> dict:
    sources = learner.skill_sources
    run_student = run_student or learner.run_student
    root = learner.root / 'l2'
    root.mkdir(parents=True, exist_ok=True)
    lineage = Lineage(root / 'lineage.jsonl')
    parent_source = sources.policy.decode() if sources.policy is not None else FIXED_SELECT
    parent_digest = _digest(parent_source)
    parent_id = parent_digest[:16]
    if parent_id not in lineage.nodes:
        lineage.record(Version(id=parent_id, parent=None, target='skill_selection', digest=parent_digest,
                               hypothesis='human-written relevance rule' if parent_source == FIXED_SELECT else ''))
    parent = lineage.nodes[parent_id]
    tasks = validation_tasks(learner, round_index)
    present = skill_ids(learner.library.bundle_path)
    runs: dict[str, dict] = {}

    def evaluate(policy_source: str) -> dict[str, float]:
        digest = _digest(policy_source)
        if digest in runs:
            return {t: r['score'] for t, r in runs[digest].items()}
        saved = sources.policy
        sources.set_policy(policy_source)
        out = {}
        try:
            for task in tasks:
                shown = sources.relevant(task['instruction'], present)
                result = run_student(learner.library, task,
                                     f"l2-{label}-{digest[:12]}-{task['task_id']}{learner.run_suffix}")
                _checked(result, 'l2 validation')       # a crash is infrastructure, not a policy score
                out[task['task_id']] = {'score': result.score, 'shown': shown, 'trace_path': result.trace_path,
                                        'gate': sources.rows(task['instruction'], present),
                                        'instruction': task['instruction']}
        finally:
            sources.set_policy(saved.decode() if saved is not None else None)
        runs[digest] = out
        return {t: r['score'] for t, r in out.items()}

    before = evaluate(parent_source)
    archive_versions = [{'id': parent_id, 'target': 'skill_selection', 'source': parent_source,
                         'validation': {'passed': sum(v >= 1.0 for v in before.values()), 'total': len(before),
                                        'tasks': {t: {'score': r['score'], 'shown': r['shown']}
                                                  for t, r in runs[parent_digest].items()}},
                         'traces': []}]
    archive = write_archive(root / 'archive' / label, archive_versions)
    for task_id, r in runs[parent_digest].items():
        d = archive / parent_id / 'tasks' / task_id
        d.mkdir(parents=True, exist_ok=True)
        (d / 'gate.json').write_text(json.dumps({'instruction': r['instruction'], 'skills': r['gate'],
                                                 'shown': r['shown'], 'score': r['score']}, indent=1))
        if r['score'] < 1.0 and r['trace_path'] and Path(r['trace_path']).exists():
            rows = [scrub(json.loads(l)) for l in Path(r['trace_path']).read_text().splitlines() if l.strip()]
            (d / 'trace.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows))
    summary = {'parent': parent_id, 'validation_tasks': len(tasks), 'parent_passed': sum(v >= 1.0 for v in before.values())}
    proposal = architect.propose(archive, BRIEF, run_id=f'architect-{learner.arm}-{label}{learner.run_suffix}')
    summary.update(status=proposal['status'], cost_usd=proposal.get('cost_usd'), turns=proposal.get('turns'))
    if proposal['status'] != 'proposed':
        return summary
    if proposal['target'] != 'skill_selection':
        summary['status'] = 'wrong_target'
        summary['target'] = proposal['target']
        return summary
    module_dir, digest = write_module(root / 'modules', proposal)
    paths = {module_dir: proposal['code']}
    result = promote(lineage, parent, proposal, module_dir, digest,
                     lambda d: evaluate(parent_source if d is None else paths[d]), parent_dir=None)
    summary.update(result, hypothesis=proposal['hypothesis'][:300])
    if result['promoted']:
        sources.set_policy(proposal['code'])
    return summary

"""Self-practice between stream tasks: local-only drills on families near the learning frontier.

One round (``PracticeRound.run``):
  competence.practice_targets → fresh variants from the dedicated practice seed range
  → current library, local student only (no teacher, no cloud cost)
  → competence/skill statistics updated like stream tasks
  → failures queued in repair_queue.jsonl for W4-2; one summary row in practice_rounds.jsonl
    (the data source for "what I practised / learned" reports).

Practice never sees stream or eval instances: seeds come from SPLITS['practice'] and a
persistent cursor so later rounds do not repeat earlier drills.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import time
from typing import Callable

from core.evolution.competence import CompetenceModel
from core.evolution.contracts import Candidate, RunResult
from core.evolution.mutator import bundle_digest
from core.evolution.stream import skill_calls
from core.evolution.stream_tasks import NEGATIVE_FAMILIES, SPLITS, make_task, split_of


class PracticeRound:
    def __init__(self, root: Path, competence: CompetenceModel, *,
                 run_student: Callable[[Candidate, dict, str], RunResult]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.competence, self.run_student = competence, run_student
        self.state_path = self.root / 'practice_state.json'

    def _next_seeds(self, family: str, count: int) -> list[int]:
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'cursor': {}}
        start = state['cursor'].get(family, SPLITS['practice'].start)
        seeds = list(range(start, start + count))
        if not seeds or split_of(seeds[-1]) != 'practice':
            raise ValueError(f'practice seed range exhausted for {family}')
        state['cursor'][family] = start + count
        self.state_path.write_text(json.dumps(state, sort_keys=True))
        return seeds

    def _log(self, name: str, row: dict) -> None:
        with (self.root / name).open('a') as out:
            out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    def run(self, library: Candidate, budget_tasks: int, *, k: int = 2, label: str = '') -> dict:
        targets = [t for t in self.competence.practice_targets(k=k + len(NEGATIVE_FAMILIES))
                   if t['family'] not in NEGATIVE_FAMILIES][:k]
        summary = {'label': label, 'created': time.time(), 'library': library.digest[:16],
                   'targets': targets, 'families': {}, 'tasks': 0, 'passed': 0}
        if not targets or budget_tasks <= 0:
            self._log('practice_rounds.jsonl', summary)
            return summary
        shares = [budget_tasks // len(targets) + (i < budget_tasks % len(targets)) for i in range(len(targets))]
        for target, share in zip(targets, shares):
            family = target['family']
            fam = summary['families'].setdefault(family, {'tasks': 0, 'passed': 0, 'p_before': target['p_success']})
            for seed in self._next_seeds(family, share):
                task = make_task(family, seed)
                result = self.run_student(library, task, f"practice-{label}-{task['task_id']}")
                calls = skill_calls(result)
                solved = result.score >= 1.0
                for call in calls:
                    if call.get('skill_id'):
                        self.competence.record_skill(call['skill_id'], call['success'] and solved)
                self.competence.record_task(family, solved)
                fam['tasks'] += 1
                fam['passed'] += int(solved)
                for skill_id in sorted({c['skill_id'] for c in calls if c.get('skill_id') and c['success']}):
                    if solved:
                        self._log('skill_successes.jsonl', {'skill_id': skill_id, 'family': family, 'seed': seed})
                if not solved:
                    self._log('repair_queue.jsonl', {
                        'task_id': task['task_id'], 'family': family, 'seed': seed, 'label': label,
                        'skill_ids_called': sorted({c['skill_id'] for c in calls if c.get('skill_id')}),
                        'failure': {'status': result.status, 'score': result.score,
                                    'trace_path': result.trace_path}})
            fam['p_after'] = round(self.competence.family(family).p_success, 4)
            summary['tasks'] += fam['tasks']
            summary['passed'] += fam['passed']
        self._log('practice_rounds.jsonl', summary)
        return summary


# ---------------------------------------------------------------- W4-2 library maintenance
REPAIR_MIN_FAILURES = 2
REPAIR_PRIOR_SUCCESSES = 2
MERGE_OVERLAP = 0.7


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def _desc_words(text: str) -> set[str]:
    return set(re.findall(r'[a-z0-9]{3,}', text.casefold()))


def _trace(path) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def maintain_library(root: Path, library: Candidate, competence: CompetenceModel, *,
                     propose: Callable[[Candidate, dict], Candidate] | None,
                     run_student: Callable[[Candidate, dict, str], RunResult] | None) -> tuple[Candidate, dict]:
    """One maintenance pass: repair at most one skill, retire weak/idle ones, record merge candidates.

    A repaired version replaces the old one only if it passes the queued failure tasks AND up to two
    tasks the skill previously solved; retirement writes a new bundle (new digest, parent recorded),
    keeping the removed source in retired.json. Every change goes to library_changes.jsonl.
    """
    root = Path(root)
    state_path = root / 'maintenance_state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'handled': []}
    manifest = json.loads((Path(library.bundle_path) / 'manifest.json').read_text())
    present = {item['skill_id']: item for item in manifest['skills']}
    summary = {'repair': None, 'retired': [], 'merge_candidates': []}

    def log(change: str, **fields):
        with (root / 'library_changes.jsonl').open('a') as out:
            out.write(json.dumps({'change': change, 'created': time.time(), **fields}, ensure_ascii=False) + '\n')

    # 1. repair
    queue = [q for q in _jsonl(root / 'repair_queue.jsonl') if q['task_id'] not in state['handled']]
    by_skill: dict[str, list[dict]] = {}
    for q in queue:
        for skill_id in q.get('skill_ids_called', []):
            if skill_id in present:
                by_skill.setdefault(skill_id, []).append(q)
    target = next((sid for sid in sorted(by_skill) if len(by_skill[sid]) >= REPAIR_MIN_FAILURES), None)
    if target and propose is not None and run_student is not None:
        failures = by_skill[target]
        tasks = [make_task(q['family'], q['seed']) for q in failures]
        prior = [r for r in _jsonl(root / 'skill_successes.jsonl') if r['skill_id'] == target][-REPAIR_PRIOR_SUCCESSES:]
        checks = tasks + [make_task(r['family'], r['seed']) for r in prior]
        feedback = {'task_id': tasks[0]['task_id'], 'instruction': tasks[0]['instruction'],
                    'failure_reason': f'the skill {target} was called and the external check failed on '
                                      f'{len(tasks)} practice tasks; repair it under the same skill_id',
                    'trace': _trace(failures[0]['failure'].get('trace_path'))}
        accepted, error = False, None
        try:
            child = propose(library, feedback)
            accepted = all(run_student(child, task, f"repair-check-{child.candidate_id}-{task['task_id']}").score >= 1.0
                           for task in checks)
        except Exception as exc:                       # a failed proposal is data, not a crash
            error = f'{type(exc).__name__}: {exc}'
        summary['repair'] = {'skill_id': target, 'accepted': accepted, 'checked': len(checks)}
        if accepted:
            log('repair', skill_id=target, parent=library.candidate_id, child=child.candidate_id, checked=len(checks))
            library = child
        else:
            log('repair_rejected', skill_id=target, parent=library.candidate_id, checked=len(checks), error=error)
        state['handled'] += [q['task_id'] for q in failures]

    # 2. retire
    retire = [c for c in competence.retirement_candidates() if c['skill_id'] in present]
    if retire:
        source = Path(library.bundle_path)
        stage = root / 'bundles' / f'.stage-{time.time_ns()}'
        shutil.copytree(source, stage)
        keep = [item for item in manifest['skills'] if item['skill_id'] not in {c['skill_id'] for c in retire}]
        retired_log = json.loads((root / 'retired.json').read_text()) if (root / 'retired.json').exists() else []
        for cand in retire:
            item = present[cand['skill_id']]
            retired_log.append({'skill_id': cand['skill_id'], 'why': cand['why'], 'descriptor': item,
                                'source': (source / item['entrypoint'].split(':')[0]).read_text(),
                                'from_library': library.candidate_id})
            competence.skills[cand['skill_id']].status = 'retired'
            summary['retired'].append(cand['skill_id'])
        (stage / 'manifest.json').write_text(json.dumps({**manifest, 'skills': keep}, sort_keys=True))
        digest = bundle_digest(stage)
        final = root / 'bundles' / digest
        if final.exists():
            shutil.rmtree(stage)
        else:
            stage.rename(final)
        (root / 'retired.json').write_text(json.dumps(retired_log, ensure_ascii=False, indent=1))
        child = Candidate('skill-' + digest[:16], (library.candidate_id,), 'skill', str(final.resolve()), digest,
                          'retire ' + ', '.join(summary['retired']), library.island_id)
        log('retire', skills=summary['retired'], parent=library.candidate_id, child=child.candidate_id)
        library = child
        present = {item['skill_id']: item for item in keep}

    # 3. merge candidates (recorded only)
    active = [sid for sid in sorted(present) if competence.skills.get(sid) and competence.skills[sid].status == 'active']
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            wa, wb = _desc_words(present[a]['description']), _desc_words(present[b]['description'])
            if wa and wb and len(wa & wb) / len(wa | wb) > MERGE_OVERLAP:
                summary['merge_candidates'].append([a, b])
    if summary['merge_candidates']:
        log('merge_candidates', pairs=summary['merge_candidates'])
    state_path.write_text(json.dumps(state))
    return library, summary

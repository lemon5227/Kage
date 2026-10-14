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
import time
from typing import Callable

from core.evolution.competence import CompetenceModel
from core.evolution.contracts import Candidate, RunResult
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

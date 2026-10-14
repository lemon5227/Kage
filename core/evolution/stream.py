"""Continual-learning stream: one task after another, learning between tasks.

Vertical slice of docs/plans/self-evolving-proactive-agent-2026-10-14.md:

    competence → (proactive help?) → student attempt → environment feedback
      → on failure / help request: teacher demonstration (cached per task, clean state)
      → skill proposal from the verified demonstration → re-check on the source task
      → library grows (skill status 'trial', becomes 'active' on first real successful use)

Execution, teacher and proposal are injected callables, so the same loop runs with
real models on the Mac (scripts/experiments/stream_run.py) and with fakes in tests.
Evaluation checkpoints never learn and never update competence.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Callable

from core.evolution.competence import CompetenceModel
from core.evolution.contracts import Candidate, RunResult

ARMS = {
    'A0': {'learn': False, 'help': 'never'},       # raw student
    'A4': {'learn': True, 'help': 'after_failure'}, # skill library, passive help
    'A5': {'learn': True, 'help': 'proactive'},     # skill library + competence-driven help
}


def _trace_rows(result: RunResult) -> list[dict]:
    path = Path(result.trace_path) if result.trace_path else None
    if not path or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def skill_calls(result: RunResult) -> list[dict]:
    calls = []
    for row in _trace_rows(result):
        action = row.get('action') if isinstance(row.get('action'), dict) else {}
        if action.get('name') == 'skill_call':
            args = action.get('arguments') if isinstance(action.get('arguments'), dict) else {}
            obs = row.get('observation') if isinstance(row.get('observation'), dict) else {}
            calls.append({'skill_id': args.get('skill_id'), 'success': bool(obs.get('success')),
                          'actor': obs.get('actor')})
    return calls


WRITE_ACTIONS = {'write_file', 'fs_write', 'fs_apply'}


def wrote_files(result: RunResult) -> bool:
    for row in _trace_rows(result):
        action = row.get('action') if isinstance(row.get('action'), dict) else {}
        obs = row.get('observation') if isinstance(row.get('observation'), dict) else {}
        if action.get('name') in WRITE_ACTIONS and obs.get('success'):
            return True
    return False


def help_requested(result: RunResult) -> bool:
    return any(chain.get('stop_reason') == 'help_requested' for chain in result.metadata.get('chain', []))


class TeacherCache:
    """Teacher solves each task once from its clean initial state; reused across arms/seeds."""
    def __init__(self, root: Path, solve: Callable[[dict], RunResult]):
        self.root, self.solve = Path(root), solve
        self.root.mkdir(parents=True, exist_ok=True)
        self.fresh_calls = 0

    def get(self, task: dict) -> RunResult:
        path = self.root / f"{task['task_id']}.json"
        if path.exists():
            return RunResult(**json.loads(path.read_text()))
        self.fresh_calls += 1
        result = self.solve(task)
        path.write_text(json.dumps(asdict(result), ensure_ascii=False, default=str))
        return result


class StreamLearner:
    def __init__(self, root: Path, arm: str, *, bootstrap: Candidate,
                 run_student: Callable[[Candidate, dict, str], RunResult],
                 teacher: TeacherCache | None,
                 propose_skill: Callable[[Candidate, dict, RunResult], Candidate] | None,
                 help_cost: float = 0.25):
        if arm not in ARMS:
            raise ValueError(f'unknown arm {arm}')
        if ARMS[arm]['learn'] and (teacher is None or propose_skill is None):
            raise ValueError('learning arms need a teacher and a skill proposer')
        self.root, self.arm, self.cfg = Path(root), arm, ARMS[arm]
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_student, self.teacher, self.propose_skill = run_student, teacher, propose_skill
        self.help_cost = help_cost
        self.competence_path = self.root / 'competence.json'
        self.competence = CompetenceModel.load(self.competence_path)
        state_path = self.root / 'library.json'
        if state_path.exists():
            data = json.loads(state_path.read_text())
            self.library = Candidate(**{**data, 'parent_ids': tuple(data['parent_ids'])})
        else:
            self.library = bootstrap
        self.done = {json.loads(l)['task_id'] for l in (self.root / 'stream.jsonl').read_text().splitlines()} \
            if (self.root / 'stream.jsonl').exists() else set()

    # ------------------------------------------------------------------ helpers
    def _log(self, name: str, row: dict) -> None:
        with (self.root / name).open('a') as out:
            out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    def _save(self) -> None:
        self.competence.save(self.competence_path)
        (self.root / 'library.json').write_text(json.dumps(asdict(self.library), default=str))

    def _learn(self, task: dict, demo: RunResult) -> dict:
        info = {'attempted': True, 'accepted': False}
        try:
            child = self.propose_skill(self.library, task, demo)
        except Exception as exc:                 # proposal failures are data, not crashes
            info['error'] = f'{type(exc).__name__}: {exc}'
            return info
        info['child'] = child.candidate_id
        check = self.run_student(child, task, f"{task['task_id']}-learn-check")
        info.update(check_score=check.score, check_skill_calls=skill_calls(check))
        if check.score >= 1.0 and any(c['success'] for c in info['check_skill_calls']):
            self.library = child
            info['accepted'] = True
        return info

    # ------------------------------------------------------------------ stream
    def step(self, task: dict) -> dict:
        if task['task_id'] in self.done:
            raise ValueError('task already consumed by this stream; side effects are not replayed')
        if task.get('split') != 'stream':
            raise ValueError('only stream-split tasks may enter the learning stream')
        family = task['family']
        row = {'task_id': task['task_id'], 'family': family, 'negative': task.get('negative', False),
               'arm': self.arm, 'index': self.competence.task_index, 'library_before': self.library.digest[:16]}
        decision = self.competence.should_request_help(family, help_cost=self.help_cost)
        ask_first = self.cfg['help'] == 'proactive' and decision['ask']
        row['help_decision'] = decision
        if ask_first:
            self.competence.record_help(family, True, when='before_attempt', reason=decision['why'])
            student = None
        else:
            student = self.run_student(self.library, task, f"{task['task_id']}-student")
            row.update(student_score=student.score, student_status=student.status,
                       skill_calls=skill_calls(student), help_requested=help_requested(student))
        solved = student is not None and student.score >= 1.0
        helped = False
        if not solved and self.cfg['help'] != 'never':
            if student is not None:
                self.competence.record_help(family, True, when='after_failure' if not row.get('help_requested')
                                            else 'student_requested', reason='feedback: not passed')
            demo = self.teacher.get(task)
            helped = True
            row.update(teacher_score=demo.score, teacher_status=demo.status)
            # Runtime-legal gate: only a verified demonstration that actually changed files
            # carries a procedure worth extracting (a read-only answer does not).
            if self.cfg['learn'] and demo.score >= 1.0 and wrote_files(demo):
                row['learning'] = self._learn(task, demo)
        for call in row.get('skill_calls', []):
            if call.get('skill_id'):
                self.competence.record_skill(call['skill_id'], call['success'] and solved)
        self.competence.record_task(family, solved, helped=helped)
        row.update(solved_by_student=solved, helped=helped, library_after=self.library.digest[:16],
                   p_success_after=self.competence.families[family].p_success)
        self.done.add(task['task_id'])
        self._save()
        self._log('stream.jsonl', row)
        return row

    def evaluate(self, tasks: list[dict], label: str) -> dict:
        """Frozen checkpoint: current library, no help, no learning, no competence update."""
        rows = []
        for task in tasks:
            if task.get('split') != 'eval':
                raise ValueError('checkpoint tasks must come from the eval split')
            result = self.run_student(self.library, task, f"{label}-{task['task_id']}")
            calls = skill_calls(result)
            rows.append({'checkpoint': label, 'task_id': task['task_id'], 'family': task['family'],
                         'negative': task.get('negative', False), 'score': result.score,
                         'status': result.status, 'skill_calls': calls, 'library': self.library.digest[:16],
                         'misuse': bool(task.get('negative') and calls)})
            self._log('checkpoints.jsonl', rows[-1])
        passed = sum(r['score'] >= 1.0 for r in rows)
        return {'checkpoint': label, 'passed': passed, 'total': len(rows),
                'misuse': sum(r['misuse'] for r in rows), 'library': self.library.digest[:16]}


# ---------------------------------------------------------------------- real wiring
def chain_runner(journal, budget, workspaces: Path, model_factory, *, skill_runner=None, cloud=False,
                 max_model_calls=6, max_steps=5, max_tool_actions=12, timeout_s=150,
                 tool_max_tokens=1024):
    """Build ``run(candidate, task, run_id) -> RunResult`` over the real Kage chain.

    Shared by scripts/experiments/stream_run.py (live models) and the integration test
    (scripted models), so the trace/skill plumbing tested is the one used on the Mac.
    """
    from core.agentic_loop import AgenticLoop
    from core.evolution.agent_provider import KageChainProvider
    from core.evolution.contracts import RunSpec
    from core.evolution.runner import EvolutionRunner
    from core.evolution.skills import SkillCatalog
    loop_cls = type('StreamLoop', (AgenticLoop,), {'MAX_STEPS': max_steps, 'TOOL_MAX_TOKENS': tool_max_tokens})

    def run(candidate, task, run_id):
        catalog = None if cloud else SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=skill_runner)
        chain = KageChainProvider(model_factory(run_id), model_label='teacher' if cloud else 'student',
                                  provider_mode='cloud' if cloud else 'live', max_model_calls=max_model_calls,
                                  agentic_loop_cls=loop_cls, skill_catalog=catalog,
                                  skill_context_mode='preview', max_tool_actions=max_tool_actions)
        if cloud:
            chain.RESERVATION_OUTPUT_CAP = 6144
        runner = EvolutionRunner(journal, budget, Path(workspaces), chain)
        return runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id, task['task_id'],
                                                   max_steps=1, timeout_s=timeout_s))
    return run

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

import copy
from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Callable

from core.evolution.budget import BudgetExhaustedError
from core.evolution.competence import CompetenceModel
from core.evolution.contracts import Candidate, RunResult
from core.evolution.leakage import screen_lessons
from core.evolution.relevance import InstructionSpace, SkillSources, TaskClusters, skill_ids

ARMS = {
    'A0': {'learn': False, 'help': 'never'},       # raw student
    'A1': {'learn': False, 'help': 'never'},       # same total budget spent on local retries
    'A3': {'learn': 'memory', 'help': 'after_failure'},  # verified demonstrations as trajectory memory
    'A4': {'learn': True, 'help': 'after_failure'}, # skill library, passive help
    'A5-e0': {'learn': True, 'help': 'proactive'},  # E-0 slice: skill library + family-keyed competence help
    # E-1 diagnosis: skills were accepted after passing only their source task, so narrow skills got in.
    # A4g also verifies on the last `verify_family` same-family stream tasks already seen and, if that
    # fails, asks once (`generalize`) for a rewrite covering the failing instructions.
    'A4g': {'learn': True, 'help': 'after_failure', 'verify_family': 2, 'generalize': 1},
    # A4m = A4g + the A3 trajectory memory: skills and verified demonstrations together.
    'A4m': {'learn': 'both', 'help': 'after_failure', 'verify_family': 2, 'generalize': 1},
    # P3 (E-2). All arms below see only what the agent can see: tasks are grouped by agent-side
    # clusters instead of benchmark families, and knowledge is injected only when relevant (gate).
    # A4mG = A4m + gate + clusters: isolates the gate's effect (E-1c unseen-family interference).
    'A4mG': {'learn': 'both', 'help': 'after_failure', 'verify_family': 2, 'generalize': 1,
             'gate': True, 'clusters': True},
    # C3: A4mG plus teacher-written, task-scoped lessons extracted from each verified browser demo.
    'A4mGL': {'learn': 'both', 'help': 'after_failure', 'verify_family': 2, 'generalize': 1,
              'gate': True, 'clusters': True, 'lessons': True},
    # C3 control: only the lessons above, with no demonstration memory and no skills.
    'AGL': {'learn': 'lessons', 'help': 'after_failure', 'gate': True, 'clusters': True, 'lessons': True},
    # A5 = A4mG + proactive help: ask before trying when competence is low and nothing relevant is
    # known; do not ask where earlier help taught nothing learnable.
    'A5': {'learn': 'both', 'help': 'proactive_gated', 'verify_family': 2, 'generalize': 1,
           'gate': True, 'clusters': True},
    # A6 = A5 + background evolution every 10 stream tasks: practice, library maintenance, and every
    # 20 tasks one architect (L2) proposal for the skill-selection policy. A6-fixed keeps the
    # human-written gate instead of the architect.
    'A6': {'learn': 'both', 'help': 'proactive_gated', 'verify_family': 2, 'generalize': 1,
           'gate': True, 'clusters': True, 'evolve': {'every': 10, 'practice': 6, 'architect_every': 20}},
    'A6-fixed': {'learn': 'both', 'help': 'proactive_gated', 'verify_family': 2, 'generalize': 1,
                 'gate': True, 'clusters': True, 'evolve': {'every': 10, 'practice': 6, 'architect_every': 0}},
}


class InfrastructureError(RuntimeError):
    """The model server or sandbox failed (runner status 'crashed'): not a capability result.

    Nothing is recorded for that task; the job stops and a restart resumes from it.
    """


class TeacherBudgetExhausted(RuntimeError):
    """The teacher ledger refused the call: learning arms must stop the stream (checkpoints still run)."""


def _checked(result: RunResult, what: str) -> RunResult:
    if result.status == 'budget_exhausted':
        raise TeacherBudgetExhausted(f'{what}: teacher budget exhausted at run {result.run_id}; not recorded')
    if result.status == 'crashed':
        raise InfrastructureError(f'{what}: run {result.run_id} crashed (infrastructure); not recorded')
    return result


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


def changed_state(task: dict, result: RunResult) -> bool:
    """Did the run do something worth learning a procedure from? Files written, or (browser task)
    a verified save — a passing browser negative saves nothing, so it never counts."""
    if task.get('fixture') is not None:
        return result.score >= 1.0 and not task.get('negative')
    return wrote_files(result)


_ACTED = re.compile(r'"acted":\s*(\{[^{}]*\})')


def _browser_rows(result: RunResult) -> list[dict]:
    """A browser demonstration as label-level steps: element refs are page-local, labels carry over."""
    rows = []
    for row in _trace_rows(result):
        action = row.get('action') if isinstance(row.get('action'), dict) else {}
        obs = row.get('observation') if isinstance(row.get('observation'), dict) else {}
        match = _ACTED.search(str(obs.get('content', '')))
        if action.get('name') != 'browser_act' or not obs.get('success') or not match:
            continue
        acted = json.loads(match.group(1))
        args = {'operation': acted.get('operation'), 'target': acted.get('label')}
        if 'value' in acted:
            args['value'] = acted['value']
        rows.append({'action': {'name': 'browser_act', 'arguments': args},
                     'observation': {'success': True,
                                     'content': 'done (earlier page: pick the target_ref with this label from the current observation)'}})
    return rows


def help_requested(result: RunResult) -> bool:
    return any(chain.get('stop_reason') == 'help_requested' for chain in result.metadata.get('chain', []))


_WORD = re.compile(r'[a-z0-9_]+')
MEMORY_OBS_CHARS = 1500
MEMORY_TOTAL_CHARS = 4000
MEMORY_MIN_JACCARD = 0.2


def _words(text: str) -> set[str]:
    return set(_WORD.findall(str(text).casefold()))


class MemoryStore:
    """A3 memory: verified teacher demonstrations, retrieved by instruction overlap only.

    Rows keep the visible action (name, arguments) and observation (success, truncated
    content); never scoring data, and never the task family, which the agent does not know.
    """
    def __init__(self, path: Path, min_jaccard: float = MEMORY_MIN_JACCARD, similarity: Callable | None = None):
        # Gated arms pass the arm's InstructionSpace.similarity with relevance.RELEVANCE_MIN: with
        # Jaccard >= 0.2, unseen families matched other families' demonstrations (0.17-0.24 on stream-v1).
        self.path, self.min_jaccard, self.similarity = Path(path), min_jaccard, similarity

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def add(self, task: dict, demo: RunResult) -> bool:
        if not changed_state(task, demo):
            return False
        rows = _browser_rows(demo) if task.get('fixture') is not None else []
        for row in [] if task.get('fixture') is not None else _trace_rows(demo):
            action = row.get('action') if isinstance(row.get('action'), dict) else {}
            obs = row.get('observation') if isinstance(row.get('observation'), dict) else {}
            rows.append({'action': {'name': action.get('name'), 'arguments': action.get('arguments', {})},
                         'observation': {'success': bool(obs.get('success')),
                                         'content': str(obs.get('content', ''))[:MEMORY_OBS_CHARS]}})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as out:
            out.write(json.dumps({'instruction': task['instruction'], 'rows': rows}, ensure_ascii=False) + '\n')
        return True

    def retrieve(self, instruction: str) -> list[dict]:
        query, best = _words(instruction), (0.0, None)
        for entry in self.entries():
            if self.similarity is not None:
                score = self.similarity(instruction, entry['instruction'])
            else:
                words = _words(entry['instruction'])
                score = len(query & words) / len(query | words) if query | words else 0.0
            if score > best[0]:
                best = (score, entry)
        if best[1] is None or best[0] < self.min_jaccard:
            return []
        rows = list(best[1]['rows'])
        while rows and len(json.dumps(rows, ensure_ascii=False)) > MEMORY_TOTAL_CHARS:
            rows.pop(0)                        # drop the oldest rows first; the write stays
        return rows


class TeacherCache:
    """Teacher solves each task once from its clean initial state; reused across arms/seeds."""
    def __init__(self, root: Path, solve: Callable[[dict], RunResult]):
        self.root, self.solve = Path(root), solve
        self.root.mkdir(parents=True, exist_ok=True)
        self.fresh_calls = 0

    def get(self, task: dict) -> RunResult:
        # Arms running in parallel share this cache: one lock per task, atomic writes, so a
        # demonstration is paid for once and never read half-written.
        import fcntl
        import os
        path = self.root / f"{task['task_id']}.json"
        with open(self.root / f".{task['task_id']}.lock", 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                return RunResult(**json.loads(path.read_text()))
            self.fresh_calls += 1
            result = _checked(self.solve(task), 'teacher')      # a crashed demo is never cached
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(asdict(result), ensure_ascii=False, default=str))
            os.replace(tmp, path)
            return result


class StreamLearner:
    def __init__(self, root: Path, arm: str, *, bootstrap: Candidate,
                 run_student: Callable[[Candidate, dict, str], RunResult],
                 teacher: TeacherCache | None,
                 propose_skill: Callable[[Candidate, dict, RunResult], Candidate] | None,
                 help_cost: float = 0.25, memory: MemoryStore | None = None, run_suffix: str = '',
                 skill_sources: SkillSources | None = None, evolver: Callable | None = None,
                 playbook=None, extract_lessons: Callable | None = None):
        if arm not in ARMS:
            raise ValueError(f'unknown arm {arm}')
        learn = ARMS[arm]['learn']
        if ARMS[arm].get('lessons') and (playbook is None or extract_lessons is None):
            raise ValueError('lesson arms need a playbook and a lesson extractor')
        if ARMS[arm].get('gate') and learn in (True, 'both') and skill_sources is None:
            raise ValueError('gated skill arms need the SkillSources shared with the student runner')
        if ARMS[arm].get('evolve') and evolver is None:
            raise ValueError('evolving arms need an evolver')
        if learn in ('memory', 'both'):
            if teacher is None or memory is None:
                raise ValueError('memory arms need a teacher and a memory store')
            if learn == 'both' and propose_skill is None:
                raise ValueError('the combined arm also needs a skill proposer')
        elif learn == 'lessons':
            if teacher is None:
                raise ValueError('lesson arms need a teacher')
        elif learn and (teacher is None or propose_skill is None):
            raise ValueError('learning arms need a teacher and a skill proposer')
        self.memory = memory
        self.playbook, self.extract_lessons = playbook, extract_lessons
        # A restarted job must not reuse run ids: the runner caches a crashed run under its id and
        # would return that crash again without calling the model (Kaggle v6, A3).
        self.run_suffix = run_suffix
        self.root, self.arm, self.cfg = Path(root), arm, ARMS[arm]
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_student, self.teacher, self.propose_skill = run_student, teacher, propose_skill
        self.help_cost = help_cost
        self.skill_sources, self.evolver = skill_sources, evolver
        space = skill_sources.space if skill_sources is not None else InstructionSpace(self.root / 'space.json')
        self.clusters = TaskClusters(self.root / 'clusters.json', space) if self.cfg.get('clusters') else None
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

    def _key(self, task: dict) -> str:
        """What the agent groups this task under: its own cluster when the arm uses clusters."""
        if self.clusters is None:
            return task['family']
        cid, _ = self.clusters.nearest(task['instruction'])
        return cid if cid is not None else self.clusters.assign(task['instruction'], generator=task['family'])

    def _knows(self, task: dict) -> bool:
        """Is any learned skill or demonstration relevant enough to be shown for this task?"""
        if self.skill_sources is not None and self.skill_sources.relevant(
                task['instruction'], skill_ids(self.library.bundle_path)):
            return True
        return bool(self.memory is not None and self.memory.retrieve(task['instruction']))

    def _family_history(self, task: dict) -> list[dict]:
        """Up to `verify_family` earlier same-family (same-cluster) stream tasks, most recent first."""
        k = int(self.cfg.get('verify_family', 0))
        log = self.root / 'stream.jsonl'
        if not k or not log.exists():
            return []
        from core.evolution.stream_tasks import make_task
        rows = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        if self.clusters is not None:
            # Replays tasks this agent saw in the same cluster; `family` only names their generator.
            key = self._key(task)
            same = [(r['family'], r['task_id']) for r in rows if r.get('cluster') == key
                    and r['task_id'] != task['task_id']]
        else:
            same = [(r['family'], r['task_id']) for r in rows if r['family'] == task['family']
                    and r['task_id'] != task['task_id'] and not r.get('negative')]
        return [make_task(fam, int(tid.rsplit('-', 1)[1])) for fam, tid in reversed(same[-k:])]

    def _verify(self, child: Candidate, task: dict, info: dict, tag: str) -> tuple[bool, list[dict]]:
        """Source task must pass with a successful skill call; each earlier same-family task must pass too."""
        self._expose(child, [task] + self._family_history(task))
        check = _checked(self.run_student(child, task, f"{task['task_id']}-{tag}{self.run_suffix}"), 'learn check')
        calls = skill_calls(check)
        info.setdefault('checks', []).append({'tag': tag, 'source_score': check.score})
        if not (check.score >= 1.0 and any(c['success'] for c in calls)):
            return False, []
        failing = []
        for other in self._family_history(task):
            res = _checked(self.run_student(child, other, f"{other['task_id']}-{tag}-for-{task['task_id']}{self.run_suffix}"),
                           'family check')
            ok = res.score >= 1.0 and any(c['success'] for c in skill_calls(res))
            info['checks'][-1].setdefault('family', []).append({'task_id': other['task_id'], 'passed': ok})
            if not ok:
                failing.append(other)
        return not failing, failing

    def _learn(self, task: dict, demo: RunResult) -> dict:
        info = {'attempted': True, 'accepted': False}
        if self.cfg['learn'] == 'lessons':
            # Browser lessons are extracted by the caller; nothing is stored in memory or the library.
            info.update(kind='lessons')
            return info
        if task.get('fixture') is not None and self.cfg['learn'] not in ('memory', 'both'):
            info['skill'] = 'not applicable to browser tasks'
            return info
        if self.cfg['learn'] in ('memory', 'both'):
            stored = self.memory.add(task, demo)
            if self.cfg['learn'] == 'memory':
                info.update(kind='memory', accepted=stored)
                return info
            info['memory_stored'] = stored
            if task.get('fixture') is not None:
                # File skills cannot drive a page: browser tasks learn by memory only (C v1).
                info.update(kind='memory', accepted=stored, skill='not applicable to browser tasks')
                return info
        if self.cfg.get('verify_family'):
            info['verify_tasks'] = [t['task_id'] for t in self._family_history(task)]
        try:
            child = self.propose_skill(self.library, task, demo)
        except Exception as exc:                 # proposal failures are data, not crashes
            info['error'] = f'{type(exc).__name__}: {exc}'
            return info
        info['child'] = child.candidate_id
        # Provisional gate entries for the candidate; restored below unless it is adopted.
        snapshot = copy.deepcopy(self.skill_sources.sources) if self.skill_sources is not None else None
        try:
            return self._check_and_adopt(task, demo, child, info)
        finally:
            if snapshot is not None and not info['accepted']:
                self.skill_sources.sources = snapshot
                self.skill_sources.add([], [])          # persist the restored state

    def _check_and_adopt(self, task: dict, demo: RunResult, child: Candidate, info: dict) -> dict:
        if not self.cfg.get('verify_family'):
            self._expose(child, [task])
            check = _checked(self.run_student(child, task, f"{task['task_id']}-learn-check{self.run_suffix}"), 'learn check')
            info.update(check_score=check.score, check_skill_calls=skill_calls(check))
            if check.score >= 1.0 and any(c['success'] for c in info['check_skill_calls']):
                self._adopt(child, [task])
                info['accepted'] = True
            return info
        ok, failing = self._verify(child, task, info, 'learn-check')
        for attempt in range(int(self.cfg.get('generalize', 0))):
            if ok or not failing:
                break
            # Visible instructions only (never hidden cases): the skill must also cover these variants.
            hint = ('The extracted skill passed the demonstrated task but failed these earlier tasks of the same '
                    'family. Rewrite it so one skill covers all of them through parameters:\n'
                    + '\n'.join('- ' + t['instruction'] for t in failing))
            try:
                child = self.propose_skill(self.library, task, demo, hint=hint)
            except Exception as exc:
                info['generalize_error'] = f'{type(exc).__name__}: {exc}'
                break
            info.update(child=child.candidate_id, generalized=True)
            ok, failing = self._verify(child, task, info, f'generalize{attempt + 1}')
        if ok:
            self._adopt(child, [task] + self._family_history(task))
            info['accepted'] = True
        return info

    def _changed(self, child: Candidate) -> list[str]:
        """Skill ids that are new or rewritten in ``child`` relative to the current library."""
        def items(bundle):
            try:
                manifest = json.loads((Path(bundle) / 'manifest.json').read_text())
            except (OSError, ValueError):
                return {}
            return {i['skill_id']: i.get('digest') for i in manifest.get('skills', [])}
        before, after = items(self.library.bundle_path), items(child.bundle_path)
        return [sid for sid, digest in after.items() if before.get(sid) != digest]

    def _expose(self, child: Candidate, tasks: list[dict]) -> None:
        """Gate: let the candidate's new skills be seen on the tasks it is being verified on."""
        if self.skill_sources is not None:
            self.skill_sources.add(self._changed(child), [t['instruction'] for t in tasks])

    def _adopt(self, child: Candidate, verified_on: list[dict]) -> None:
        """Install a verified library; record which instructions its new/changed skills were verified on."""
        self._expose(child, verified_on)
        self.library = child

    # ------------------------------------------------------------------ stream
    def step(self, task: dict) -> dict:
        if task['task_id'] in self.done:
            raise ValueError('task already consumed by this stream; side effects are not replayed')
        if task.get('split') != 'stream':
            raise ValueError('only stream-split tasks may enter the learning stream')
        family = task['family']
        # The agent's own grouping (cluster) when the arm uses clusters; the benchmark label otherwise.
        key = self.clusters.assign(task['instruction'], generator=family) if self.clusters else family
        row = {'task_id': task['task_id'], 'family': family, 'negative': task.get('negative', False),
               'arm': self.arm, 'index': self.competence.task_index, 'library_before': self.library.digest[:16]}
        if self.clusters is not None:
            row['cluster'] = key
        decision = self.competence.should_request_help(key, help_cost=self.help_cost)
        policy = self.cfg['help']
        if policy == 'proactive_gated':
            # Ask before trying only when competence is low AND nothing learned looks relevant (after
            # learning, try first again); never where earlier help here taught nothing learnable.
            decision['knows'] = self._knows(task)
            decision['help_useful'] = self.competence.help_useful(key)
            ask_first = decision['ask'] and not decision['knows'] and decision['help_useful']
        else:
            ask_first = policy == 'proactive' and decision['ask']
        row['help_decision'] = decision
        if ask_first:
            self.competence.record_help(key, True, when='before_attempt', reason=decision['why'])
            student = None
        else:
            student = _checked(self.run_student(self.library, task, f"{task['task_id']}-student{self.run_suffix}"), 'student')
            row.update(student_score=student.score, student_status=student.status,
                       skill_calls=skill_calls(student), help_requested=help_requested(student))
        solved = student is not None and student.score >= 1.0
        helped = False
        may_ask = policy != 'never' and (policy != 'proactive_gated' or decision['help_useful'])
        if not solved and policy != 'never' and not may_ask:
            row['help_declined'] = 'earlier help on this cluster taught nothing learnable'
            self.competence.record_help(key, False, when='after_failure', reason=row['help_declined'])
        if not solved and may_ask:
            if student is not None:
                self.competence.record_help(key, True, when='after_failure' if not row.get('help_requested')
                                            else 'student_requested', reason='feedback: not passed')
            demo = self.teacher.get(task)
            helped = True
            row.update(teacher_score=demo.score, teacher_status=demo.status)
            # Runtime-legal gate: only a verified demonstration that actually changed files
            # carries a procedure worth extracting (a read-only answer does not).
            if self.cfg['learn'] and demo.score >= 1.0 and changed_state(task, demo):
                row['learning'] = self._learn(task, demo)
                if self.cfg.get('lessons') and task.get('fixture') is not None:
                    try:
                        extracted = self.extract_lessons(task, demo, student)
                    except BudgetExhaustedError as exc:
                        # Same stop as a refused demonstration: learning ends, checkpoints still run.
                        raise TeacherBudgetExhausted(f"lessons for {task['task_id']}: {exc}") from exc
                    lessons = [{**lesson, 'scope': 'task'} for lesson in extracted]
                    lessons, rejected = screen_lessons(lessons, task)
                    outcomes = self.playbook.add(lessons, source_task=task['task_id'], family=task['family'],
                                                 trigger=task['instruction'])
                    self.playbook.save()
                    row['learning']['lessons'] = {
                        'n': len(lessons), 'rejected': len(rejected),
                        'rejected_values': sorted({v for r in rejected for v in r['leaked']})[:20],
                        'outcomes': outcomes}
                    if any(outcome in ('added', 'merged') for outcome in outcomes):
                        row['learning']['accepted'] = True
            learning = row.get('learning') or {}
            self.competence.record_help_outcome(key, bool(learning.get('accepted') or learning.get('memory_stored')))
        for call in row.get('skill_calls', []):
            if call.get('skill_id'):
                self.competence.record_skill(call['skill_id'], call['success'] and solved)
        self.competence.record_task(key, solved, helped=helped)
        row.update(solved_by_student=solved, helped=helped, library_after=self.library.digest[:16],
                   p_success_after=self.competence.families[key].p_success)
        self.done.add(task['task_id'])
        self._save()
        self._log('stream.jsonl', row)
        return row

    def maybe_evolve(self) -> dict | None:
        """Run the background evolution round that is due (every `every` stream tasks); resumable.

        Rounds already logged in evolution.jsonl are not repeated; a crash inside a round reruns it.
        """
        cfg = self.cfg.get('evolve')
        if not cfg:
            return None
        log = self.root / 'evolution.jsonl'
        rounds = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
        due = len(self.done) // cfg['every']
        if len(rounds) >= due:
            return None
        label = f"e{due * cfg['every']}"
        before = self.library.candidate_id
        summary = self.evolver(self, label=label, round_index=due,
                               architect=bool(cfg.get('architect_every')) and (due * cfg['every']) % cfg['architect_every'] == 0)
        summary.update(label=label, library_before=before, library_after=self.library.candidate_id)
        self._save()
        self._log('evolution.jsonl', summary)
        return summary

    def evaluate(self, tasks: list[dict], label: str) -> dict:
        """Frozen checkpoint: current library, no help, no learning, no competence update.

        Resumable per task: rows already logged for this label are reused, not rerun.
        """
        log = self.root / 'checkpoints.jsonl'
        done = {}
        if log.exists():
            for line in log.read_text().splitlines():
                row = json.loads(line) if line.strip() else None
                if row and row.get('checkpoint') == label:
                    done[row['task_id']] = row
        rows = []
        for task in tasks:
            if task.get('split') != 'eval':
                raise ValueError('checkpoint tasks must come from the eval split')
            if task['task_id'] in done:
                rows.append(done[task['task_id']])
                continue
            result = _checked(self.run_student(self.library, task, f"{label}-{task['task_id']}{self.run_suffix}"), 'checkpoint')
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
                 tool_max_tokens=1024, mode='plain', memory: MemoryStore | None = None, playbook=None,
                 playbook_similarity=None, playbook_min: float = 0.0,
                 recovery_bundle: Path | None = None, skill_preview: str = 'preview', gate=None,
                 browser_timeout_s=360, browser_max_model_calls=10, browser_max_steps=8):
    """Build ``run(candidate, task, run_id) -> RunResult`` over the real Kage chain.

    Shared by scripts/experiments/stream_run.py (live models) and the integration test
    (scripted models), so the trace/skill plumbing tested is the one used on the Mac.

    ``gate`` (relevance.SkillSources): only skills verified near this instruction are visible;
    with none, the catalog is empty and the prompt equals the raw student's (A0).
    Browser tasks (``fixture``) run on ``BrowserChainProvider`` / ``BrowserCloudProvider`` with their own
    protocol (10 calls / 8 steps, one page action per step; same for every arm); memory mode shows the
    remembered demonstration as earlier turns.
    """
    from core.agentic_loop import AgenticLoop
    from core.evolution.agent_provider import KageChainProvider
    from core.evolution.contracts import RunSpec
    from core.evolution.bundle import RecoveryPolicy
    from core.evolution.retries import LocalRetryProvider
    from core.evolution.sandbox import ProcessSkillRunner
    from core.evolution.runner import EvolutionRunner
    from core.evolution.skills import SkillCatalog
    loop_cls = type('StreamLoop', (AgenticLoop,), {'MAX_STEPS': max_steps, 'TOOL_MAX_TOKENS': tool_max_tokens})

    if mode not in {'plain', 'retry', 'memory'} or (mode == 'memory') != (memory is not None):
        raise ValueError('mode must be plain/retry/memory; memory mode needs a MemoryStore')

    class MemoryChain(KageChainProvider):
        def __init__(self, *args, demonstration, **kwargs):
            super().__init__(*args, **kwargs)
            self.demonstration = demonstration

        def generate_step(self, task_def, step, history, workspace_dir):
            return super().generate_step(task_def, step, self.demonstration + history, workspace_dir)

    def browser_chain(task, run_id, call_cap=browser_max_model_calls, step_cap=browser_max_steps, shown=None):
        # C: a page-scoped browser chain on a fresh local fixture; file skills do not apply here.
        from core.computer_use.experiment import BrowserChainProvider, BrowserCloudProvider
        cls = BrowserCloudProvider if cloud else BrowserChainProvider
        browser_loop = type('StreamLoop', (AgenticLoop,), {'MAX_STEPS': step_cap, 'TOOL_MAX_TOKENS': tool_max_tokens})
        lessons = [] if cloud or playbook is None else playbook.select(
            task['instruction'], similarity=playbook_similarity, min_score=playbook_min)
        if shown is not None:
            shown[:] = lessons
        kwargs = dict(model_label='teacher' if cloud else 'student', provider_mode='cloud' if cloud else 'live',
                      max_model_calls=call_cap, agentic_loop_cls=browser_loop, max_loop_steps=min(step_cap, call_cap),
                      settle_saves=True, extra_guidance=playbook.render(lessons) if lessons else '')
        demonstration = memory.retrieve(task['instruction']) if mode == 'memory' else []
        chain = cls(model_factory(run_id), task, **kwargs)
        if demonstration:
            step = chain.generate_step
            chain.generate_step = lambda task_def, n, history, ws: step(task_def, n, demonstration + history, ws)
        return chain

    def run(candidate, task, run_id):
        if task.get('fixture') is not None:
            shown = []
            chain = (LocalRetryProvider(lambda calls=browser_max_model_calls, steps=browser_max_steps:
                                        browser_chain(task, run_id, calls, steps, shown),
                                        task, browser_max_model_calls, browser_max_steps)
                     if mode == 'retry' else browser_chain(task, run_id, shown=shown))
            runner = EvolutionRunner(journal, budget, Path(workspaces), chain)
            result = runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id, task['task_id'],
                                                         max_steps=1, timeout_s=max(timeout_s, browser_timeout_s)))
            if shown:
                playbook.record_use(shown, result.score >= 1.0)
                playbook.save()
            return result
        catalog = None if cloud else SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=skill_runner)
        if catalog is not None and gate is not None:
            # Gated out = an empty catalog, which is exactly what A0 runs with (bootstrap bundle).
            catalog = catalog.restrict(gate.relevant(task['instruction'], catalog.digests))
        preview_mode = 'preview' if catalog is not None and not catalog.digests else skill_preview
        lessons = playbook.select(task['instruction'], similarity=playbook_similarity,
                                  min_score=playbook_min) if playbook is not None else []
        guidance = playbook.render(lessons) if playbook is not None else ''

        def make_chain(call_cap=max_model_calls, step_cap=max_steps):
            cls = loop_cls if step_cap == max_steps else type('StreamLoop', (AgenticLoop,), {
                'MAX_STEPS': step_cap, 'TOOL_MAX_TOKENS': tool_max_tokens})
            kwargs = dict(model_label='teacher' if cloud else 'student', provider_mode='cloud' if cloud else 'live',
                          max_model_calls=call_cap, agentic_loop_cls=cls, skill_catalog=catalog,
                          skill_context_mode=preview_mode, max_tool_actions=max_tool_actions,
                          extra_guidance=guidance,
                          recovery_policy=RecoveryPolicy.from_bundle(recovery_bundle, runner=skill_runner or ProcessSkillRunner())
                          if recovery_bundle is not None else None)
            if mode == 'memory':
                return MemoryChain(model_factory(run_id), demonstration=memory.retrieve(task['instruction']), **kwargs)
            return KageChainProvider(model_factory(run_id), **kwargs)

        chain = LocalRetryProvider(make_chain, task, max_model_calls, max_steps) if mode == 'retry' else make_chain()
        if cloud:
            chain.RESERVATION_OUTPUT_CAP = 6144
        runner = EvolutionRunner(journal, budget, Path(workspaces), chain)
        result = runner.run(candidate, task, RunSpec(run_id, candidate.candidate_id, task['task_id'],
                                                     max_steps=1, timeout_s=timeout_s))
        if lessons:
            playbook.record_use(lessons, result.score >= 1.0)
            playbook.save()
        return result
    return run

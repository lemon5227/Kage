"""Competence model: what the agent believes it can do, per task family and per skill.

This is the hub of the proactive loop (see docs/plans/self-evolving-proactive-agent-2026-10-14.md):
- execution loop asks it whether to request help before/while attempting a task;
- background evolution asks it which family to practise next;
- skill maintenance asks it which skills are unused or harmful;
- user-facing reports quote it.

Only runtime-legal signals may be recorded: the agent's own outcomes after user/environment
feedback, its own self-checks, and help events. Hidden evaluation answers never enter here.
Beta(1,1) priors keep the maths transparent and cheap on a 16GB laptop.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class FamilyStats:
    successes: int = 0
    failures: int = 0
    helped: int = 0          # tasks where a teacher/user had to step in
    seen: int = 0            # tasks observed (including help-only ones)
    help_learned: int = 0    # help events that left something learned (skill accepted / demo stored)
    help_wasted: int = 0     # help events that taught nothing (failed or read-only demonstration)

    def posterior(self, prior=(1.0, 1.0)):
        return prior[0] + self.successes, prior[1] + self.failures

    @property
    def p_success(self) -> float:
        a, b = self.posterior()
        return a / (a + b)

    @property
    def p_success_std(self) -> float:
        a, b = self.posterior()
        return math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))


@dataclass
class SkillStats:
    calls: int = 0
    successes: int = 0
    last_task_index: int = -1
    status: str = 'trial'    # trial -> active -> retired

    @property
    def success_rate(self) -> float:
        return self.successes / self.calls if self.calls else 0.0


@dataclass
class CompetenceModel:
    families: dict[str, FamilyStats] = field(default_factory=dict)
    skills: dict[str, SkillStats] = field(default_factory=dict)
    task_index: int = 0
    help_log: list[dict] = field(default_factory=list)

    # ---------- persistence ----------
    @classmethod
    def load(cls, path: str | Path) -> 'CompetenceModel':
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(families={k: FamilyStats(**v) for k, v in data.get('families', {}).items()},
                   skills={k: SkillStats(**v) for k, v in data.get('skills', {}).items()},
                   task_index=int(data.get('task_index', 0)), help_log=list(data.get('help_log', [])))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'families': {k: asdict(v) for k, v in self.families.items()},
                              'skills': {k: asdict(v) for k, v in self.skills.items()},
                              'task_index': self.task_index, 'help_log': self.help_log},
                             ensure_ascii=False, sort_keys=True, indent=1)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.competence-')
        with os.fdopen(fd, 'w') as handle:
            handle.write(payload)
        os.replace(tmp, path)

    # ---------- recording ----------
    def family(self, name: str) -> FamilyStats:
        return self.families.setdefault(name, FamilyStats())

    def record_task(self, family: str, success: bool, *, helped: bool = False,
                    skill_id: str | None = None, skill_success: bool | None = None) -> None:
        """Record one finished task. A helped task is not a student success."""
        stats = self.family(family)
        stats.seen += 1
        if helped:
            stats.helped += 1
            stats.failures += 1      # the student alone did not solve it
        elif success:
            stats.successes += 1
        else:
            stats.failures += 1
        if skill_id is not None:
            self.record_skill(skill_id, bool(skill_success))
        self.task_index += 1

    def record_skill(self, skill_id: str, success: bool) -> None:
        stats = self.skills.setdefault(skill_id, SkillStats())
        stats.calls += 1
        stats.successes += int(success)
        stats.last_task_index = self.task_index
        if stats.status == 'trial' and stats.successes >= 1:
            stats.status = 'active'   # adoption is decided by real use, not one validation

    def record_help(self, family: str, asked: bool, *, when: str, reason: str = '') -> None:
        self.help_log.append({'task_index': self.task_index, 'family': family, 'asked': asked,
                              'when': when, 'p_success': round(self.family(family).p_success, 4),
                              'reason': reason[:300]})

    def record_help_outcome(self, family: str, learned: bool) -> None:
        stats = self.family(family)
        if learned:
            stats.help_learned += 1
        else:
            stats.help_wasted += 1

    # ---------- decisions ----------
    def help_useful(self, family: str, *, max_wasted: int = 2) -> bool:
        """Is asking here still worth it? No once `max_wasted` helps taught nothing and none taught anything."""
        stats = self.family(family)
        return not (stats.help_wasted >= max_wasted and stats.help_learned == 0)

    def should_request_help(self, family: str, *, value: float = 1.0, help_cost: float = 0.25,
                            min_observations: int = 2) -> dict:
        """Ask before attempting when expected loss of a failed attempt exceeds the help cost.

        With fewer than ``min_observations`` the agent tries first (exploration), so that
        competence is measured rather than assumed. Returns an explanation for logs/UI.
        """
        stats = self.family(family)
        p_fail = 1.0 - stats.p_success
        observed = stats.successes + stats.failures
        ask = observed >= min_observations and p_fail * value > help_cost
        return {'ask': ask, 'family': family, 'p_success': round(stats.p_success, 4),
                'observations': observed, 'expected_loss': round(p_fail * value, 4), 'help_cost': help_cost,
                'why': ('low competence' if ask else
                        'exploring: too few observations' if observed < min_observations else 'competent enough')}

    def practice_targets(self, k: int = 1, *, min_seen: int = 1) -> list[dict]:
        """Families worth practising: frequent ones whose success is near the learning frontier (≈50%)."""
        total = sum(s.seen for s in self.families.values()) or 1
        ranked = []
        for name, stats in self.families.items():
            if stats.seen < min_seen:
                continue
            p = stats.p_success
            frontier = 4 * p * (1 - p)          # 1.0 at p=0.5, 0 at 0 or 1
            ranked.append({'family': name, 'score': round(stats.seen / total * (0.25 + frontier), 6),
                           'p_success': round(p, 4), 'seen': stats.seen})
        ranked.sort(key=lambda row: (-row['score'], row['family']))
        return ranked[:k]

    def retirement_candidates(self, *, min_calls: int = 3, min_rate: float = 0.34,
                              idle_tasks: int = 30) -> list[dict]:
        out = []
        for skill_id, stats in self.skills.items():
            if stats.status == 'retired':
                continue
            if stats.calls >= min_calls and stats.success_rate < min_rate:
                out.append({'skill_id': skill_id, 'why': f'low success {stats.success_rate:.2f} over {stats.calls} calls'})
            elif self.task_index - max(stats.last_task_index, 0) > idle_tasks:
                out.append({'skill_id': skill_id, 'why': f'unused for {self.task_index - stats.last_task_index} tasks'})
        return out

    def summary(self) -> dict:
        return {'task_index': self.task_index,
                'families': {k: {'p_success': round(v.p_success, 3), 'seen': v.seen, 'helped': v.helped}
                             for k, v in sorted(self.families.items())},
                'skills': {k: {'status': v.status, 'calls': v.calls, 'rate': round(v.success_rate, 3)}
                           for k, v in sorted(self.skills.items())}}

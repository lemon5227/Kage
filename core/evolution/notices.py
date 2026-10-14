"""Proactive messages from the learning loop: ask for help, report learning, confirm adoption.

Every number in a notice comes from a result file or the competence model; nothing here
asks a model to produce figures. Notices are appended to ``notices.jsonl`` (default
``~/.kage/notices.jsonl``) and delivered by :class:`NoticeSource`, a Heartbeat trigger
source, so the existing proactive policy (quiet hours, snooze, mute, feedback) applies.

Kinds (fixed shape)::

    {"kind": "help_request" | "learning_report" | "adoption_confirm",
     "title": "<=40 chars", "body": "<=300 chars", "evidence": {...},
     "created": "...", "needs_reply": bool, "id": "..."}

At most ``DAILY_OPTIONAL_CAP`` notices that do not need a reply are written per day.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import uuid

from core.proactive import make_notification

DAILY_OPTIONAL_CAP = 3
DEFAULT_PATH = Path('~/.kage/notices.jsonl')
KINDS = {'help_request', 'learning_report', 'adoption_confirm'}


def _notice(kind: str, title: str, body: str, evidence: dict, needs_reply: bool,
            now: datetime.datetime | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f'unknown notice kind {kind!r}')
    return {'id': uuid.uuid4().hex[:12], 'kind': kind, 'title': title[:40], 'body': body[:300],
            'evidence': evidence, 'created': (now or datetime.datetime.now()).isoformat(),
            'needs_reply': needs_reply}


def help_request(competence, family: str, *, now=None) -> dict | None:
    """Ask the user for a demonstration when the competence model says the family is weak."""
    stats = competence.family(family)
    tried = stats.successes + stats.failures
    if tried == 0:
        return None
    body = (f'{family} 这类任务我最近 {tried} 次里自己只完成了 {stats.successes} 次'
            f'（估计成功率 {stats.p_success:.0%}）。你能演示一次吗？不方便的话我会去问教师模型。')
    return _notice('help_request', f'想请你教我：{family}', body,
                   {'family': family, 'successes': stats.successes, 'attempts': tried,
                    'p_success': round(stats.p_success, 4)}, True, now)


def learning_report(practice_round: dict, *, accepted_skills: list[str] = (), retired_skills: list[str] = (),
                    now=None) -> dict | None:
    """Summarize one practice/evolution round from its practice_rounds.jsonl row."""
    if not practice_round.get('tasks') and not accepted_skills and not retired_skills:
        return None
    parts = []
    for family, fam in sorted(practice_round.get('families', {}).items()):
        change = ''
        if 'p_before' in fam and 'p_after' in fam:
            change = f'，估计成功率 {fam["p_before"]:.0%}→{fam["p_after"]:.0%}'
        parts.append(f'{family} 练了 {fam["tasks"]} 题、对 {fam["passed"]} 题{change}')
    if accepted_skills:
        parts.append('新技能通过验证：' + '、'.join(accepted_skills))
    if retired_skills:
        parts.append('停用：' + '、'.join(retired_skills))
    return _notice('learning_report', '我刚练习完一轮', '；'.join(parts) + '。',
                   {'round': practice_round.get('label'), 'tasks': practice_round.get('tasks', 0),
                    'passed': practice_round.get('passed', 0), 'families': practice_round.get('families', {}),
                    'accepted_skills': list(accepted_skills), 'retired_skills': list(retired_skills)}, False, now)


def adoption_confirm(skill_id: str, description: str, *, writes_files: bool, validation: dict, now=None) -> dict | None:
    """Ask before a new file-writing skill is used on the user's real tasks (stays 'trial' until then)."""
    if not writes_files:
        return None
    body = (f'我学会了「{skill_id}」：{description[:120]}。它会修改文件，验证结果 '
            f'{validation.get("passed", 0)}/{validation.get("total", 0)}。要在你的日常任务里启用吗？')
    return _notice('adoption_confirm', f'启用新技能？{skill_id}', body,
                   {'skill_id': skill_id, 'validation': validation}, True, now)


class NoticeStore:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path).expanduser()

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def add(self, notice: dict | None) -> bool:
        """Append unless empty or over the daily cap for optional notices."""
        if notice is None:
            return False
        if not notice['needs_reply']:
            day = notice['created'][:10]
            optional_today = sum(1 for r in self.rows() if not r.get('needs_reply') and str(r.get('created', ''))[:10] == day)
            if optional_today >= DAILY_OPTIONAL_CAP:
                return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as out:
            out.write(json.dumps(notice, ensure_ascii=False) + '\n')
        return True


def record_reply(path: str | Path, action: dict, now: datetime.datetime | None = None) -> dict:
    """The user accepted a notice that needed a reply (their click is the consent)."""
    row = {'notice_id': action.get('notice_id'), 'kind': action.get('kind'), 'evidence': action.get('evidence', {}),
           'accepted': (now or datetime.datetime.now()).isoformat()}
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


class NoticeSource:
    """Heartbeat trigger source: delivers each stored notice once, as a proactive notification."""

    def __init__(self, store: NoticeStore, cursor_path: str | Path | None = None):
        self.store = store
        self.cursor_path = Path(cursor_path) if cursor_path else store.path.with_suffix('.delivered.json')

    def _delivered(self) -> set[str]:
        if not self.cursor_path.exists():
            return set()
        return set(json.loads(self.cursor_path.read_text()))

    async def collect(self, now: datetime.datetime) -> list[dict]:
        delivered = self._delivered()
        fresh = [r for r in self.store.rows() if r.get('id') not in delivered]
        out = []
        for row in fresh:
            note = make_notification(f"evolution:{row['kind']}", f"{row['title']}\n{row['body']}",
                                     type_=row['kind'], now=now,
                                     action={'type': 'notice_reply', 'notice_id': row['id'], 'kind': row['kind'],
                                             'evidence': row.get('evidence', {})}
                                     if row['needs_reply'] else None)
            out.append(note)
            delivered.add(row['id'])
        if fresh:
            self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
            self.cursor_path.write_text(json.dumps(sorted(delivered)))
        return out

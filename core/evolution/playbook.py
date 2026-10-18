"""Two-level playbook of lessons learned from failures (SkillRL / ACE style).

Lessons arrive in the same teacher call that proposes a skill (optional ``lessons`` field),
so the playbook adds no teacher requests. ``general`` lessons are always injected (at most
``GENERAL_CAP``); ``task`` lessons are retrieved by word overlap with the instruction, or by
the caller's instruction similarity against the raw triggers, top 2 either way.
Updates are incremental: a new lesson whose words overlap an existing one by more than
``MERGE_OVERLAP`` refreshes that entry instead of growing or rewriting the whole playbook,
so the playbook does not collapse into ever shorter summaries. Lessons are kept even when
the accompanying skill is rejected: the failure itself is what they describe.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time

GENERAL_CAP = 8
TASK_TOP_K = 2
MAX_LESSONS_PER_PROPOSAL = 3
MAX_FIELD_CHARS = 200
MERGE_OVERLAP = 0.6
_WORD = re.compile(r'[a-z0-9_]{3,}')


def _words(text: str) -> set[str]:
    return set(_WORD.findall(str(text).casefold()))


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def parse_lessons(proposal: dict) -> list[dict]:
    """Optional ``lessons`` from a teacher proposal; malformed entries are dropped, long ones cut."""
    raw = proposal.get('lessons') if isinstance(proposal, dict) else None
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict) or item.get('scope') not in {'general', 'task'}:
            continue
        lesson = {'scope': item['scope']}
        for key in ('when', 'do', 'avoid'):
            lesson[key] = str(item.get(key) or '')[:MAX_FIELD_CHARS].strip()
        if lesson['do'] or lesson['avoid']:
            out.append(lesson)
        if len(out) == MAX_LESSONS_PER_PROPOSAL:
            break
    return out


class Playbook:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: list[dict] = json.loads(self.path.read_text())['entries'] if self.path.exists() else []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix='.playbook-')
        with os.fdopen(fd, 'w') as handle:
            json.dump({'entries': self.entries}, handle, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def add(self, lessons: list[dict], *, source_task: str, family: str = '', trigger: str = '') -> list[str]:
        """Merge or append each lesson; returns 'merged'/'added'/'dropped' per lesson."""
        outcomes = []
        raw_trigger = str(trigger)[:400]
        for lesson in lessons:
            text = _words(' '.join(lesson.get(k, '') for k in ('when', 'do', 'avoid')))
            match = next((e for e in self.entries if e['scope'] == lesson['scope'] and
                          _overlap(text, _words(' '.join(e[k] for k in ('when', 'do', 'avoid')))) > MERGE_OVERLAP), None)
            if match is not None:
                match.update({k: lesson[k] or match[k] for k in ('when', 'do', 'avoid')})
                match['count'] += 1
                match['sources'] = (match['sources'] + [source_task])[-10:]
                if raw_trigger:
                    match['triggers'] = (list(match.get('triggers') or []) + [raw_trigger])[-5:]
                match['updated'] = time.time()
                outcomes.append('merged')
                continue
            if lesson['scope'] == 'general' and sum(e['scope'] == 'general' for e in self.entries) >= GENERAL_CAP:
                outcomes.append('dropped')
                continue
            self.entries.append({**lesson, 'id': f"L{len(self.entries) + 1}", 'family': family,
                                 'trigger': ' '.join(sorted(_words(trigger)))[:400],
                                 'triggers': [raw_trigger] if raw_trigger else [], 'count': 1,
                                 'sources': [source_task], 'created': time.time(), 'updated': time.time(),
                                 'injected': 0, 'injected_success': 0})
            outcomes.append('added')
        return outcomes

    def select(self, instruction: str, similarity=None, min_score: float = 0.0) -> list[dict]:
        general = [e for e in self.entries if e['scope'] == 'general'][:GENERAL_CAP]
        if similarity is not None:
            # Browser lessons carry raw instructions; retrieve by their semantic similarity.
            scored = []
            for entry in self.entries:
                if entry['scope'] != 'task':
                    continue
                triggers = entry.get('triggers') or []
                if not triggers:
                    continue
                score = max(similarity(instruction, t) for t in triggers)
                if score > 0 and score >= min_score:
                    scored.append((score, entry['updated'], entry))
            scored.sort(key=lambda row: (-row[0], -row[1]))
            return general + [entry for _, _, entry in scored[:TASK_TOP_K]]
        words = _words(instruction)
        scored = []
        for entry in self.entries:
            if entry['scope'] != 'task':
                continue
            score = _overlap(words, _words(entry['trigger'] + ' ' + entry['when']))
            if score > 0:
                scored.append((score, entry['updated'], entry))
        scored.sort(key=lambda row: (-row[0], -row[1]))
        return general + [entry for _, _, entry in scored[:TASK_TOP_K]]

    @staticmethod
    def render(entries: list[dict]) -> str:
        if not entries:
            return ''
        lines = ['Lessons from earlier tasks (advice, not ground truth):']
        for e in entries:
            parts = [f"when {e['when']}" if e['when'] else '', f"do: {e['do']}" if e['do'] else '',
                     f"avoid: {e['avoid']}" if e['avoid'] else '']
            lines.append('- ' + '; '.join(p for p in parts if p))
        return '\n'.join(lines) + '\n'

    def record_use(self, entries: list[dict], success: bool) -> None:
        ids = {e['id'] for e in entries}
        for entry in self.entries:
            if entry['id'] in ids:
                entry['injected'] += 1
                entry['injected_success'] += int(success)

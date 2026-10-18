"""Teacher-written lessons for browser tasks (C3).

C2 showed that a remembered demonstration is retrieved but rarely followed, and a raw
click list does not carry the rule that makes it work on another instance. This module
asks the teacher, from a verified label-level demonstration and the student's failed
attempt, for one or two generic rules for OTHER tasks of the same kind.
"""
from __future__ import annotations

import json

from core.evolution.budget import BudgetExhaustedError
from core.evolution.playbook import parse_lessons
from core.evolution.stream import _browser_rows

MAX_INPUT_BYTES = 24000
MAX_LESSONS = 2
OUTPUT_TOKENS = 600
# The provider adds model/parameter fields around the messages; keep room so the whole
# serialized request (not just the messages) stays under the frozen byte cap.
_REQUEST_HEADROOM = 512

LESSON_PROMPT = (
    "You write transferable lessons for a small browser agent. You are given the task instruction, "
    "the teacher's successful label-level steps, and the student's failed label-level steps. "
    "Write 1-2 rules that would let the small model succeed on OTHER tasks of the same kind. "
    "The rules must be generic: never include instance values (names, numbers, emails, hotel names, totals). "
    "State when the rule applies, what to do, and what to avoid. "
    'Reply with ONLY a JSON object: {"lessons": [{"when": "...", "do": "...", "avoid": "..."}]}.'
)


def _line(row: dict) -> str:
    """One label-level step: ``click "Show more rows"`` or ``fill "Total" = "1143"``."""
    args = (row.get('action') or {}).get('arguments') or {}
    operation, target = str(args.get('operation') or ''), str(args.get('target') or '')
    if 'value' in args:
        return f'{operation} "{target}" = "{args["value"]}"'
    return f'{operation} "{target}"'


def _messages(task: dict, demo, student) -> list[dict]:
    """Prompt messages; long step lists are cut until the serialized request fits the cap."""
    instruction = str(task.get('instruction') or '')
    teacher_steps = [_line(row) for row in _browser_rows(demo)]
    student_steps = [_line(row) for row in _browser_rows(student)] if student is not None else []
    while True:
        content = (f'Task instruction:\n{instruction}\n\n'
                   'Teacher successful steps:\n'
                   + ('\n'.join('- ' + step for step in teacher_steps) or '- (none)') + '\n\n'
                   'Student failed steps:\n'
                   + ('\n'.join('- ' + step for step in student_steps) or '- (none)'))
        messages = [{'role': 'system', 'content': LESSON_PROMPT},
                    {'role': 'user', 'content': content}]
        if len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) <= MAX_INPUT_BYTES - _REQUEST_HEADROOM:
            return messages
        # The instruction is never truncated; only the step lists give way.
        if len(teacher_steps) >= len(student_steps) and teacher_steps:
            teacher_steps.pop()
        elif student_steps:
            student_steps.pop()
        else:
            return messages


def _parse(raw: str) -> list[dict]:
    """JSON after optional fences/leading text; every browser lesson is task-scoped."""
    text = str(raw or '')
    start = text.find('{')
    if start < 0:
        return []
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return []
    raw_lessons = value.get('lessons') if isinstance(value, dict) else None
    if not isinstance(raw_lessons, list):
        return []
    lessons = [{**item, 'scope': 'task'} for item in raw_lessons if isinstance(item, dict)]
    return parse_lessons({'lessons': lessons})[:MAX_LESSONS]


def extract_lessons(model, budget, *, task: dict, demo, student, run_id: str) -> list[dict]:
    """Ask the teacher for at most two lessons; ``[]`` on any non-budget model failure."""
    messages = _messages(task, demo, student)
    reservation = budget.reserve(MAX_INPUT_BYTES, OUTPUT_TOKENS, call_type='lesson', run_id=run_id)
    response = None
    try:
        try:
            response = model.generate(messages=messages, max_tokens=OUTPUT_TOKENS, temperature=0.0)
        except BudgetExhaustedError:
            raise
        except Exception:
            return []
        if getattr(response, 'error', None):
            return []
        return _parse(getattr(response, 'text', ''))
    finally:
        budget.settle(reservation, getattr(response, 'usage', None))

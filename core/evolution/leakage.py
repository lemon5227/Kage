"""Deterministic leak screening for learned lessons and guidance-free training samples (R1).

A lesson that names an instance's answer (its total, hotel, note value or file name) teaches
that answer instead of the procedure, and a training sample that still contains the runbook
teaches the student to expect guidance. Both screens are simple, model-free checks that run
before storage and before writing a sample.
"""
from __future__ import annotations

import re

_QUOTED = re.compile(r'"([^"]{3,})"|\'([^\']{3,})\'')
_INSTRUCTION_NUMBER = re.compile(r'(?<![\w,])(-?\d[\d,]*)(?![\w,])')
_NUMBER_TOKEN = re.compile(r'(?<![\w,])(-?\d[\d,]*)(?![\w,])')
_NUMERIC = re.compile(r'^-?[\d,]+$')
_PLAIN_WORD = re.compile(r'^[A-Za-z_]+$')
_GENERIC_LABEL_KEYS = ('submit', 'query_label', 'category_label', 'apply_label')


def _as_value(value) -> str | None:
    """A string or non-boolean number as text; booleans and other types are not instance values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _walk(value):
    """Every string/number inside a JSON-like value, dict keys included.

    Single plain words are generic vocabulary (log levels, column names), not instance data;
    numbers, multi-word strings and mixed strings (emails, paths, log lines) are kept.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(key)
            yield from _walk(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)
        return
    if isinstance(value, str):
        if len(value) >= 4 and not _PLAIN_WORD.match(value):
            yield value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if abs(value) >= 10:
            yield str(value)


def _browser_values(fixture: dict, criteria: dict) -> set[str]:
    """This browser instance's answer and fixture data (no generic UI labels)."""
    values: set[str] = set()
    record = (criteria.get('expected') or {}).get('record')
    if isinstance(record, dict):
        values.update(v for v in (_as_value(item) for item in record.values()) if v)
    for field in fixture.get('fields') or []:
        if isinstance(field, dict) and isinstance(field.get('initial'), str):
            values.add(field['initial'])
    for row in fixture.get('rows') or []:
        if isinstance(row, dict):
            values.update(v for v in (_as_value(row.get(k)) for k in ('item', 'qty', 'price')) if v)
    for item in fixture.get('items') or []:
        if isinstance(item, dict):
            values.update(v for v in (_as_value(item.get(k)) for k in ('name', 'city', 'id')) if v)
    note = fixture.get('note') or []
    for line in note[1:]:
        text = str(line)
        if ': ' in text:
            values.add(text.split(': ', 1)[1])
    return values


def _file_values(criteria: dict) -> set[str]:
    """The function/file names and every instance value inside the hidden cases."""
    values = {v for v in (criteria.get('function'), criteria.get('file')) if isinstance(v, str)}
    values.update(_walk(criteria.get('cases') or []))
    return values


def _instruction_values(instruction: str) -> set[str]:
    """Quoted substrings (len >= 3) and numbers with at least two digits."""
    values = set()
    for match in _QUOTED.finditer(instruction):
        values.add(match.group(1) if match.group(1) is not None else match.group(2))
    for match in _INSTRUCTION_NUMBER.finditer(instruction):
        token = match.group(1)
        if sum(char.isdigit() for char in token) >= 2:
            values.add(token)
    return values


def _generic_labels(fixture: dict) -> set[str]:
    """Casefolded field and button labels that belong to the UI, not to this instance."""
    labels = set()
    for field in fixture.get('fields') or []:
        if isinstance(field, dict) and isinstance(field.get('label'), str):
            labels.add(field['label'].casefold())
    for key in _GENERIC_LABEL_KEYS:
        if isinstance(fixture.get(key), str):
            labels.add(fixture[key].casefold())
    return labels


def instance_values(task: dict) -> set[str]:
    """Values specific to this instance: expected answers, fixture data, quoted strings and numbers."""
    criteria = task.get('scoring_criteria') or {}
    fixture = task.get('fixture')
    values: set[str] = set()
    if fixture is not None:
        values |= _browser_values(fixture, criteria)
    if criteria.get('type') == 'python_function':
        values |= _file_values(criteria)
    values |= _instruction_values(str(task.get('instruction') or ''))
    generic = _generic_labels(fixture) if fixture is not None else set()
    return {value for value in values if len(value) >= 2 and value.casefold() not in generic}


def _number(text: str) -> str:
    """Numeric text without grouping commas, so 1143 and 1,143 compare equal."""
    return text.replace(',', '')


def leaks(text: str, task: dict) -> list[str]:
    """Instance values found in ``text``: case-insensitive, whole words, comma-tolerant numbers."""
    text = str(text)
    tokens = {_number(token) for token in _NUMBER_TOKEN.findall(text)}
    found = []
    for value in sorted(instance_values(task)):
        if _NUMERIC.match(value):
            if _number(value) in tokens:
                found.append(value)
        elif re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', text, re.IGNORECASE):
            found.append(value)
    return found


def screen_lessons(lessons: list[dict], task: dict) -> tuple[list[dict], list[dict]]:
    """Split lessons into ``(kept, rejected)``; rejected ones carry the values they leaked."""
    kept, rejected = [], []
    for lesson in lessons:
        text = ' '.join(str(lesson.get(key) or '') for key in ('when', 'do', 'avoid'))
        leaked = leaks(text, task)
        if leaked:
            rejected.append({**lesson, 'leaked': leaked})
        else:
            kept.append(lesson)
    return kept, rejected


def _normalized(text) -> str:
    return ' '.join(str(text or '').split())


def guidance_free(messages: list[dict], guidance: list[str]) -> bool:
    """True when no message content contains any substantial (>= 20 char) guidance line."""
    contents = [_normalized(message.get('content')) for message in messages if isinstance(message, dict)]
    for item in guidance:
        for line in str(item).splitlines():
            line = _normalized(line)
            if len(line) >= 20 and any(line in content for content in contents):
                return False
    return True

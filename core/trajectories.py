"""Usage-time trajectory store: real turns become future training data (A2, roadmap §4).

Every agentic turn the user runs is recorded step by step in the student's own format
(request messages + tool list → model response), the same shape as the P4-L3 SFT data, so a
later LoRA can train on it directly. Records stay on this Mac (``~/.kage/trajectories``); they
can be listed, deleted, or switched off (config ``trajectories.enabled``). Only
``export_redacted`` produces data meant to leave the machine: e-mail addresses, phone numbers,
home-directory user names, keys/tokens, IP addresses and long digit runs are masked, and only
train-split turns with success evidence are written.

Success evidence, strongest first: the user's 👍 (``feedback == 'up'``); an automatic check
(every tool call succeeded and at least one file was written or a tool reported success);
otherwise none. A 👎 marks the turn failed whatever the checks said. About one turn in ten
(by a hash of its id) is held out as a real-scene evaluation set and never exported.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

DEFAULT_ROOT = Path('~/.kage/trajectories')
WRITE_TOOLS = {'write_file', 'fs_write', 'fs_apply', 'fs_move', 'edit_file'}
HOLDOUT_EVERY = 10


def split_of(turn_id: str) -> str:
    return 'eval' if int(hashlib.sha256(turn_id.encode()).hexdigest(), 16) % HOLDOUT_EVERY == 0 else 'train'


def _plain(response: Any) -> dict:
    return {'text': str(getattr(response, 'text', '') or ''),
            'tool_calls': list(getattr(response, 'tool_calls', None) or [])}


class RecordingProvider:
    """Wraps the main loop's model: while a turn is open, each call is appended to it."""

    def __init__(self, inner, recorder: 'TrajectoryRecorder'):
        self.inner, self.recorder = inner, recorder

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7, **kwargs):
        response = self.inner.generate(messages=messages, tools=tools, max_tokens=max_tokens,
                                       temperature=temperature, **kwargs)
        self.recorder.step(messages, tools, response)
        return response

    def __getattr__(self, name):
        return getattr(self.inner, name)


class TrajectoryRecorder:
    def __init__(self, root: str | Path = DEFAULT_ROOT, *, enabled: bool = True):
        self.root = Path(os.path.expanduser(str(root)))
        self.enabled = enabled
        self._lock = threading.Lock()
        self._open: dict | None = None

    # ------------------------------------------------------------------ recording
    def begin(self, turn_id: str, user_input: str, *, source: str = 'real', parent: str | None = None) -> None:
        """Open a turn. ``source`` is 'real' (the user's task) or 'teacher' (a teacher redo of ``parent``)."""
        if not self.enabled:
            return
        with self._lock:
            self._open = {'id': turn_id, 'created': datetime.datetime.now().isoformat(timespec='seconds'),
                          'source': source, 'user_input': user_input, 'steps': []}
            if parent:
                self._open['parent'] = parent

    def annotate(self, **fields) -> None:
        """Attach metadata to the open turn (e.g. which earlier experience was injected)."""
        with self._lock:
            if self._open is not None:
                self._open.update(fields)

    def step(self, messages, tools, response) -> None:
        with self._lock:
            if self._open is not None:
                self._open['steps'].append({'messages': json.loads(json.dumps(messages, default=str)),
                                            'tools': json.loads(json.dumps(tools or [], default=str)),
                                            'response': _plain(response)})

    def finish(self, final_text: str, tool_calls: list[dict] | None) -> dict | None:
        with self._lock:
            record, self._open = self._open, None
        if record is None:
            return None
        calls = [{'name': c.get('name'), 'success': bool(c.get('success')),
                  'error_type': c.get('error_type')} for c in (tool_calls or [])]
        wrote = sorted({str((c.get('arguments') or {}).get('path') or '') for c in (tool_calls or [])
                        if c.get('name') in WRITE_TOOLS and c.get('success')} - {''})
        record.update(final_text=final_text, tool_calls=calls, kind='task' if calls else 'chat',
                      auto_check={'all_tools_ok': bool(calls) and all(c['success'] for c in calls),
                                  'wrote_files': wrote},
                      feedback=None, split=split_of(record.get('parent') or record['id']))
        # A teacher redo shares its task's split, so a held-out task never leaks into training.
        self._write(record)
        return record

    # ------------------------------------------------------------------ user control
    def _path(self, turn_id: str) -> Path:
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', turn_id)[:80]
        return self.root / f'{safe}.json'

    def _write(self, record: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix='.tmp-')
        with os.fdopen(fd, 'w') as out:
            json.dump(record, out, ensure_ascii=False)
        os.replace(tmp, self._path(record['id']))

    def get(self, turn_id: str) -> dict | None:
        path = self._path(turn_id)
        return json.loads(path.read_text()) if path.exists() else None

    def feedback(self, turn_id: str, value: str) -> dict | None:
        if value not in ('up', 'down'):
            raise ValueError("feedback must be 'up' or 'down'")
        record = self.get(turn_id)
        if record is None:
            return None
        record['feedback'] = value
        record['feedback_at'] = datetime.datetime.now().isoformat(timespec='seconds')
        self._write(record)
        return record

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        out = []
        for path in sorted(self.root.glob('*.json')):
            try:
                r = json.loads(path.read_text())
            except ValueError:
                continue
            out.append({k: r.get(k) for k in ('id', 'created', 'kind', 'user_input', 'feedback', 'split')}
                       | {'steps': len(r.get('steps', [])), 'evidence': evidence(r)})
        return out

    def delete(self, turn_id: str | None = None) -> int:
        """Delete one record, or every record when ``turn_id`` is None."""
        targets = [self._path(turn_id)] if turn_id else list(self.root.glob('*.json')) if self.root.exists() else []
        n = 0
        for path in targets:
            if path.exists():
                path.unlink()
                n += 1
        return n


def evidence(record: dict) -> str:
    """'user' (👍), 'auto' (checks passed, not 👎), 'failed' (👎) or 'none'."""
    if record.get('feedback') == 'down':
        return 'failed'
    if record.get('feedback') == 'up':
        return 'user'
    check = record.get('auto_check') or {}
    if record.get('kind') == 'task' and check.get('all_tools_ok') and check.get('wrote_files'):
        return 'auto'
    return 'none'


# ---------------------------------------------------------------------- redaction / export
_REDACTIONS = [
    (re.compile(r'(?:sk|ghp|gho|hf|KGAT|xox[abp])[-_][A-Za-z0-9_-]{12,}'), '<TOKEN>'),
    (re.compile(r'\b(?:api[_-]?key|token|secret|password|passwd)\b\s*[:=]\s*\S+', re.I), r'<CREDENTIAL>'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '<EMAIL>'),
    (re.compile(r'(?<![\w/])\+?\d[\d\s().-]{8,}\d(?![\w/])'), '<NUMBER>'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '<IP>'),
    (re.compile(r'(/Users/|/home/)[^/\s"\']+'), r'\1USER'),
]


def redact_text(text: str, extra_names: tuple[str, ...] = ()) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    for name in extra_names:
        if name:
            text = re.sub(re.escape(name), '<NAME>', text, flags=re.I)
    return text


def _redact(value, names):
    if isinstance(value, str):
        return redact_text(value, names)
    if isinstance(value, list):
        return [_redact(v, names) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, names) for k, v in value.items()}
    return value


def _chat(messages: list[dict]) -> list[dict]:
    """Template-ready messages: tool-call arguments as objects (the model's chat template iterates them)."""
    out = []
    for m in messages:
        m = dict(m)
        if m.get('tool_calls'):
            calls = []
            for c in m['tool_calls']:
                fn = c.get('function') or c
                args = fn.get('arguments')
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {'raw': args}
                calls.append({'type': 'function', 'function': {'name': fn.get('name'), 'arguments': args or {}}})
            m['tool_calls'] = calls
        out.append(m)
    return out


def export_redacted(recorder: TrajectoryRecorder, out: str | Path, *, extra_names: tuple[str, ...] = ()) -> dict:
    """Write redacted, train-split, successful task turns as SFT rows (P4-L3 format)."""
    names = tuple(extra_names) + (os.environ.get('USER', ''),)
    rows, stats = [], {'records': 0, 'exported_turns': 0, 'held_out': 0, 'no_evidence': 0}
    for path in sorted(recorder.root.glob('*.json')) if recorder.root.exists() else []:
        record = json.loads(path.read_text())
        stats['records'] += 1
        if record.get('split') == 'eval':
            stats['held_out'] += 1
            continue
        if record.get('kind') != 'task' or evidence(record) not in ('user', 'auto'):
            stats['no_evidence'] += 1
            continue
        stats['exported_turns'] += 1
        for step in record.get('steps', []):
            r = step['response']
            target = {'role': 'assistant', 'content': r.get('text') or ''}
            if r.get('tool_calls'):
                target['tool_calls'] = r['tool_calls']
            rows.append(_redact({'task_id': record['id'], 'family': 'real', 'source': 'real',
                                 'evidence': evidence(record), 'tools': step['tools'],
                                 'messages': _chat(step['messages']), 'target': _chat([target])[0]}, names))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    stats['rows'] = len(rows)
    return stats

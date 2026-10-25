"""Usage log: what the user asked, what Kage did, whether it worked — and, after a failure, how the user did it.

User request (10-25): "搞一个日志，我使用的时候都干了啥，失败了以后能不能记录我怎么做到的". Every finished turn
(fast paths included, which the training trajectories do not record) is appended to
~/.kage/activity/YYYY-MM-DD.jsonl and rendered to a readable YYYY-MM-DD.md next to it. A failed turn asks the
user how they eventually did it; their answer ("我是这样做的：…") is attached to that entry and kept as a method
for next time (`methods.jsonl`, plus the desktop lessons when the failure was a document or settings task).

Status of a turn: ok / failed / unverified (the reply claims something was done but no tool ran — the 4B model
did this in D1) / chat / learned. Local only, never committed (memory: usage-data-local-only).
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import re
import threading

ROOT = Path('~/.kage/activity').expanduser()
CLAIM = re.compile(r'(已|已经)(打开|修改|改好|添加|加好|删除|删掉|保存|发送|设置|完成|创建)')
USER_METHOD = re.compile(r'(我是这样做的|我是这么做的|我自己|我手动|我最后|我后来|我是用|我用的是|我改成)')
SHOW_LOG = re.compile(r'(看看|查看|给我看|总结).{0,6}(使用)?日志|今天(我)?(都)?(用你)?干了(啥|什么)')
FOLLOW_UP_WINDOW_S = 2 * 3600
DOC_TOOLS = {'open_documents', 'doc_read', 'doc_replace', 'doc_append_lines', 'desktop_task'}
STATUS_MARK = {'ok': '✅', 'failed': '❌', 'unverified': '⚠️', 'chat': '💬', 'learned': '📝'}


def classify(path: str, reply: str, tools: list[dict]) -> tuple[str, str]:
    """(status, reason) of a finished turn."""
    reply = str(reply or '')
    if path == 'desktop_lesson':
        return 'learned', ''
    if path == 'open_app_fastpath':
        return ('ok', '') if reply.startswith('已打开') else ('failed', reply[:120])
    if path == 'opencli_site':
        return ('failed', reply[:120]) if re.search(r'登录|出错|失败|没有拿到|无法', reply) else ('ok', '')
    if path in ('mail_fastpath', 'calendar_fastpath'):
        return ('failed', reply[:120]) if reply.startswith(('没能读取', '这封邮件已经找不到')) else ('ok', '')
    failed = [t for t in tools if not t.get('success')]
    succeeded = [t for t in tools if t.get('success')]
    if tools and not succeeded:
        first = failed[0]
        return 'failed', f"{first.get('name')}: {first.get('error_type') or ''} {str(first.get('error_message') or '')[:100]}".strip()
    if tools and failed:
        return 'ok', f"{len(failed)} 个工具调用失败后改用其它方式完成"
    if not tools and CLAIM.search(reply):
        return 'unverified', '回答说已完成，但没有调用任何工具'
    return ('ok', '') if tools else ('chat', '')


class ActivityLog:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self._lock = threading.Lock()

    def _day(self, when: datetime.datetime) -> Path:
        return self.root / f'{when:%Y-%m-%d}.jsonl'

    def entries(self, day: datetime.date | None = None) -> list[dict]:
        path = self.root / f'{(day or datetime.date.today()):%Y-%m-%d}.jsonl'
        try:
            return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except OSError:
            return []

    def record(self, *, request: str, reply: str, path: str, tools: list[dict] | None = None) -> dict:
        now = datetime.datetime.now()
        tools = [{'name': t.get('name'), 'success': bool(t.get('success')),
                  'error_type': t.get('error_type'), 'error_message': str(t.get('error_message') or '')[:200]}
                 for t in (tools or [])]
        status, reason = classify(path, reply, tools)
        entry = {'id': f'{now:%H%M%S%f}', 'time': now.isoformat(timespec='seconds'), 'request': str(request or '')[:500],
                 'path': path, 'tools': tools, 'reply': str(reply or '')[:500], 'status': status, 'reason': reason}
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with self._day(now).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            self._render(now.date())
        return entry

    def last_failure(self, max_age_s: float = FOLLOW_UP_WINDOW_S) -> dict | None:
        now = datetime.datetime.now()
        for entry in reversed(self.entries(now.date())):
            if entry['status'] in ('failed', 'unverified'):
                age = (now - datetime.datetime.fromisoformat(entry['time'])).total_seconds()
                return entry if age <= max_age_s and not entry.get('user_method') else None
        return None

    def attach_user_method(self, text: str) -> dict | None:
        """The user explains how they did a task Kage failed: attach it to that entry and keep it as a method."""
        if not USER_METHOD.search(str(text or '')):
            return None
        target = self.last_failure()
        if target is None:
            return None
        now = datetime.datetime.now()
        with self._lock:
            entries = self.entries(now.date())
            for entry in entries:
                if entry['id'] == target['id']:
                    entry['user_method'] = {'time': now.isoformat(timespec='seconds'), 'text': str(text)[:1000]}
            self._day(now).write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
            with (self.root / 'methods.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'time': now.isoformat(timespec='seconds'), 'request': target['request'],
                                         'failure': target['reason'], 'user_method': str(text)[:1000],
                                         'tools': [t['name'] for t in target['tools']]}, ensure_ascii=False) + '\n')
            self._render(now.date())
        return target

    def summary(self, day: datetime.date | None = None) -> str:
        entries = [e for e in self.entries(day) if e['path'] != 'activity_log']
        if not entries:
            return '今天还没有使用记录。'
        counts = {s: sum(e['status'] == s for e in entries) for s in STATUS_MARK}
        lines = [f"今天共 {len(entries)} 次：成功 {counts['ok']}，失败 {counts['failed']}，"
                 f"声称完成但没动手 {counts['unverified']}，闲聊 {counts['chat']}，学到经验 {counts['learned']}。"]
        for e in [e for e in entries if e['status'] in ('failed', 'unverified')][-5:]:
            how = f"；你的做法：{e['user_method']['text'][:60]}" if e.get('user_method') else '；还没记录你的做法'
            lines.append(f"{e['time'][11:16]} {STATUS_MARK[e['status']]} {e['request'][:40]}（{e['reason'][:50]}）{how}")
        lines.append(f"完整日志：{self.root / (entries[0]['time'][:10] + '.md')}")
        return '\n'.join(lines)

    def _render(self, day: datetime.date) -> None:
        out = [f'# Kage 使用日志 {day:%Y-%m-%d}', '',
               '✅ 成功　❌ 失败　⚠️ 声称完成但没调用工具　💬 闲聊　📝 记下经验', '']
        for e in self.entries(day):
            tools = '、'.join(f"{t['name']}{'' if t['success'] else '（失败）'}" for t in e['tools']) or '无'
            out.append(f"- {e['time'][11:19]} {STATUS_MARK.get(e['status'], '')} **{e['request']}**")
            out.append(f"  - 路径：{e['path']}；工具：{tools}")
            if e['reason']:
                out.append(f"  - 原因：{e['reason']}")
            out.append(f"  - 回复：{e['reply'][:200]}")
            if e.get('user_method'):
                out.append(f"  - **你的做法**（{e['user_method']['time'][11:16]}）：{e['user_method']['text']}")
        (self.root / f'{day:%Y-%m-%d}.md').write_text('\n'.join(out) + '\n', encoding='utf-8')


FAILURE_FOLLOW_UP = ('（这次没做成，已经记进使用日志。你后来要是自己做成了，告诉我“我是这样做的：……”，'
                     '我记下来，下次照着做。）')


def wants_log(text: str) -> bool:
    return bool(SHOW_LOG.search(str(text or '')))

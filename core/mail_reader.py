"""D3: read-only access to the user's Mail.app (AppleScript, the app's scripting interface — CLI first).

`unread(limit)` lists the newest unread messages (id, date, sender, subject), `read(id)` returns one message's
text, `unread_count()` the inbox badge. Nothing is ever marked read, moved or sent. Reading a message through
AppleScript does not change its read status. Mail content stays on this Mac: summaries use the local model.
The first call asks the user to allow controlling Mail (macOS Automation prompt; granted 10-25).
"""
from __future__ import annotations

import re
import subprocess

SEP, END = '\x1f', '\x1e'           # unit / record separators: never part of a subject or an address
UNREAD_SCRIPT = '''
on run argv
	set limitN to (item 1 of argv) as integer
	set sepC to character id 31
	set endC to character id 30
	set out to ""
	tell application "Mail"
		-- Per account inbox: a "whose read status is false" filter on the unified inbox ignores the condition
		-- (it returned 409 messages for a badge of 81, read ones included).
		repeat with mb in (mailboxes of inbox)
			set msgs to (messages of mb whose read status is false)
			set n to count of msgs
			if n > limitN then set n to limitN
			set acct to ""
			try
				set acct to name of account of mb
			end try
			repeat with i from 1 to n
				set m to item i of msgs
				set out to out & (id of m) & sepC & (date received of m as «class isot» as string) & sepC & (sender of m) & sepC & (subject of m) & sepC & acct & endC
			end repeat
		end repeat
	end tell
	return out
end run
'''

READ_SCRIPT = '''
on run argv
	set wanted to (item 1 of argv) as integer
	tell application "Mail"
		set m to missing value
		repeat with mb in (mailboxes of inbox)
			set hits to (messages of mb whose id is wanted)
			if (count of hits) > 0 then
				set m to item 1 of hits
				exit repeat
			end if
		end repeat
		if m is missing value then return ""
		return (sender of m) & (character id 31) & (subject of m) & (character id 31) & (date received of m as «class isot» as string) & (character id 31) & (content of m)
	end tell
end run
'''
ASK = re.compile(r'(有|看看|查看|看一下|读一下|总结一下).{0,6}(新|未读)?(的)?(邮件|邮箱|email|mail)|(新|未读)(邮件|email)'
                 r'|(check|any|read)\b.{0,12}\b(new|unread)?\s*(e-?mails?|mails?)\b', re.I)


def _osascript(script: str, *args: str, timeout: float = 120) -> str:
    result = subprocess.run(['osascript', '-', *args], input=script, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or 'osascript failed').strip()[:300])
    return result.stdout.rstrip('\n')


def unread_count() -> int:
    return int(_osascript('tell application "Mail" to get unread count of inbox') or 0)


def unread(limit: int = 10) -> list[dict]:
    limit = max(1, min(int(limit), 50))
    rows = []
    for record in _osascript(UNREAD_SCRIPT, str(limit)).split(END):
        fields = record.strip('\n').split(SEP)
        if len(fields) == 5 and fields[0].strip():
            rows.append({'id': int(fields[0]), 'date': fields[1], 'sender': fields[2], 'subject': fields[3],
                         'account': fields[4]})
    return sorted(rows, key=lambda r: r['date'], reverse=True)[:limit]       # newest first across accounts


def read(message_id: int, max_chars: int = 4000) -> dict | None:
    import time
    text = _osascript(READ_SCRIPT, str(int(message_id)))
    if text and not text.split(SEP, 3)[-1].strip():          # body not downloaded yet: Mail fetches it on demand
        time.sleep(3)
        text = _osascript(READ_SCRIPT, str(int(message_id)))
    if not text:
        return None
    sender, subject, date, body = (text.split(SEP, 3) + ['', '', '', ''])[:4]
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    return {'id': int(message_id), 'sender': sender, 'subject': subject, 'date': date,
            'text': body[:max_chars], 'truncated': len(body) > max_chars}


def sender_name(sender: str) -> str:
    match = re.match(r'\s*"?([^"<]+?)"?\s*<', sender or '')
    return match.group(1).strip() if match else (sender or '').strip()


def list_text(rows: list[dict], total: int) -> str:
    if total == 0:
        return '没有未读邮件。'
    lines = [f'未读邮件 {total} 封，最新 {len(rows)} 封：']
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['date'][5:16].replace('T', ' ')} {sender_name(r['sender'])}：{r['subject']}")
    lines.append('想看哪封，说“读第 N 封”或“总结第 N 封”。')
    return '\n'.join(lines)


PICK = re.compile(r'(读|看|打开|总结|概括)(一下)?\s*第\s*(\d+)\s*封')
SUMMARY_PROMPT = ('用中文简要总结这封邮件（3 句以内）：谁发的、要点、需要我做什么（没有就说“无需处理”）。'
                  '只根据邮件内容，不要编造。')
_last_listed: list[dict] = []


def pick(text: str) -> tuple[str, int] | None:
    match = PICK.search(str(text or ''))
    return (('summary' if match.group(1) in ('总结', '概括') else 'read'), int(match.group(3))) if match else None


def answer_pick(text: str, summarize) -> str | None:
    """Reply to "读第 N 封 / 总结第 N 封" (N from the last list shown). summarize(prompt) -> str uses the
    local model, so the message never leaves the Mac."""
    choice = pick(text)
    if choice is None:
        return None
    mode, n = choice
    rows = _last_listed or unread(10)
    if not 1 <= n <= len(rows):
        return f'只有 {len(rows)} 封可选，请说第 1 到 {len(rows)} 封。'
    message = read(rows[n - 1]['id'])
    if message is None:
        return '这封邮件已经找不到了（可能被移动或删除）。'
    head = f"第 {n} 封｜{sender_name(message['sender'])}：{message['subject']}（{message['date'][:16].replace('T', ' ')}）"
    if not message['text']:
        return head + '\n（正文为空或还没下载）'
    if mode == 'read':
        return head + '\n' + message['text'][:1500] + ('……（后面还有）' if len(message['text']) > 1500 else '')
    return head + '\n' + summarize(f"{SUMMARY_PROMPT}\n\n发件人：{message['sender']}\n主题：{message['subject']}\n\n{message['text']}")


def answer(text: str) -> str | None:
    """Reply to "有什么新邮件 / 看看未读邮件" directly from Mail (None: not such a question)."""
    if not ASK.search(str(text or '')) or re.search(r'第\s*\d+\s*封', str(text or '')):
        return None
    try:
        rows = unread(10)
        _last_listed[:] = rows
        return list_text(rows, unread_count())
    except Exception as exc:
        return f'没能读取邮件：{exc}'

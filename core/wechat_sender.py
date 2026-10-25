"""D4b: send a WeChat text message, confirm-first, verified by OCR.

WeChat has no scripting interface and almost no accessibility tree (see wechat_reader), so sending goes through
keyboard input: ⌘F search → paste the contact name → OCR the result popup and click the exact-name entry under
a contact/group section (Return would open the web search 搜一搜) → the chat title is read back by OCR and must
equal the requested name before anything is typed → paste the text → Return → OCR checks one more bubble with
that text than before. Text goes through the clipboard (typing Chinese through key events
depends on the input method); the user's clipboard is restored afterwards.

Policy: every send needs the user's "确认" except recipients in SEND_WITHOUT_ASKING (the user's own
文件传输助手 and their second account, user decision 10-25).
"""
from __future__ import annotations

import re
import subprocess
import time

from core import wechat_reader

SEND_WITHOUT_ASKING = {'文件传输助手', 'wenbo yan'}
ASK = re.compile(r'(?:用|在)?微信(?:上|里)?(?:给|跟|和)\s*(?P<to>[^，,：:说]{1,20}?)\s*(?:发(?:个|条)?(?:消息|信息|微信)?|说)'
                 r'\s*[：:，,]?\s*(?P<text>.+)$|(?:给|跟)\s*(?P<to2>[^，,：:说]{1,20}?)\s*发(?:个|条)?微信\s*[：:，,]?\s*(?P<text2>.+)$')
CONFIRM = re.compile(r'^(确认|确定|发吧|发送|可以发|好的?发|对)[。.!！]?$')
CANCEL = re.compile(r'^(取消|不发了|算了|别发)[。.!！]?$')
_pending: dict = {}


def _osa(script: str) -> str:
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or 'osascript failed').strip()[:200])
    return result.stdout.strip()


def _keys(*steps: str) -> None:
    _osa('tell application "System Events" to tell process "WeChat"\n' + '\n'.join(steps) + '\nend tell')


def _clipboard() -> str:
    return subprocess.run(['pbpaste'], capture_output=True, text=True).stdout


def _set_clipboard(text: str) -> None:
    subprocess.run(['pbcopy'], input=text, text=True, check=True)


def _norm(text: str) -> str:
    return re.sub(r'\s+', '', str(text or '')).lower()


def _count(lines: list[str], text: str) -> int:
    key = re.sub(r'[，,。.!！?？]', '', _norm(text))[:12]
    return sum(key in re.sub(r'[，,。.!！?？]', '', _norm(line)) for line in lines)


def _main_window() -> int:
    windows = [w for w in wechat_reader.wechat_windows() if w['width'] >= 500]
    if not windows:
        raise RuntimeError('微信主窗口没有打开（可能还在登录页或已最小化）')
    return windows[0]['id']


def _read_pane() -> tuple[str, list[str]]:
    """(chat title, message texts between the title bar and the input box) of the WeChat main window."""
    image = wechat_reader.capture(_main_window())
    try:
        boxes, width, height = wechat_reader.ocr(image)
    finally:
        image.unlink(missing_ok=True)
    pane = [b for b in boxes if b['x'] > width * 0.3]
    top = [b for b in pane if b['y'] < height * 0.06]
    title = ' '.join(b['text'] for b in sorted(top, key=lambda b: b['x']) if b['text'].strip() not in ('•••', '...'))
    messages = [b['text'] for b in pane if height * 0.06 < b['y'] < height * 0.78]
    return title.strip(), messages


SECTIONS = ('联系人', '群聊', '功能', '最常使用', '最近使用')
STOP = ('查看全部', '聊天记录', '搜索网络结果', '公众号', '小程序', '视频号', '文章')


def _popup() -> dict | None:
    """The search result popup (a separate, higher-layer WeChat window)."""
    import Quartz
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if w.get('kCGWindowOwnerName', '') in ('WeChat', '微信') and w.get('kCGWindowLayer', 0) > 0:
            b = w.get('kCGWindowBounds', {})
            if b.get('Height', 0) > 100:
                return {'id': int(w['kCGWindowNumber']), 'x': b['X'], 'y': b['Y'], 'w': b['Width'], 'h': b['Height']}
    return None


def _entries(boxes: list[dict], width: float) -> list[dict]:
    """Name rows under the contact / group / function sections of the search popup. The other sections are web
    suggestions (Return on them opens 搜一搜, found in the first live test) and chat-history hits."""
    rows, inside = [], False
    for b in sorted(boxes, key=lambda b: (b['y'], b['x'])):
        text = b['text'].strip()
        if text in SECTIONS:
            inside = True
        elif any(text.endswith(stop) or text.startswith(stop) for stop in STOP):
            inside = False
        elif inside and b['x'] > width * 0.15 and not text.startswith('包含'):
            rows.append(b)
    return rows


def _search(query: str) -> tuple[dict | None, list[dict]]:
    """Type `query` into WeChat search; (popup, name rows in it). Leaves the search open."""
    _set_clipboard(query)
    _keys('keystroke "f" using command down', 'delay 0.4', 'keystroke "a" using command down',
          'keystroke "v" using command down', 'delay 1.8')
    popup = _popup()
    if popup is None:
        return None, []
    image = wechat_reader.capture(popup['id'])
    try:
        boxes, width, _ = wechat_reader.ocr(image)
    finally:
        image.unlink(missing_ok=True)
    popup['scale'] = width / popup['w']
    return popup, _entries(boxes, width)


def _similar(to: str) -> list[str]:
    """Names that look like `to` (a typo or a partial name): search shorter pieces of it, rank by similarity."""
    import difflib
    words = to.split()
    queries = [words[0]] if len(words) > 1 and len(words[0]) >= 2 else []
    if not to.isascii() and len(to) > 2:
        queries.append(to[:2])
    names: list[str] = []
    for query in queries:
        _, rows = _search(query)
        names += [r['text'].strip() for r in rows]
    _keys('key code 53')
    scored = {n: difflib.SequenceMatcher(None, _norm(to), _norm(n)).ratio() for n in names}
    return [n for n, score in sorted(scored.items(), key=lambda kv: -kv[1]) if score >= 0.4][:3]


def lookup(to: str) -> tuple[bool, list[str]]:
    """(an exact contact/group named `to` exists, similar names otherwise). Done before asking the user to
    confirm, so a wrong name is caught at once instead of after "确认"."""
    import difflib
    saved = _clipboard()
    try:
        _osa('tell application "WeChat" to activate')
        time.sleep(0.6)
        _, rows = _search(to)
        _keys('key code 53')
        if any(_norm(r['text']) == _norm(to) for r in rows):
            return True, []
        names = [r['text'].strip() for r in rows
                 if difflib.SequenceMatcher(None, _norm(to), _norm(r['text'])).ratio() >= 0.4]
        return False, names[:3] or _similar(to)
    finally:
        _set_clipboard(saved)


def _not_found(to: str, text: str, names: list[str]) -> str:
    if not names:
        return f'没有发送：微信里没有叫“{to}”的联系人或群，名字是不是说错了？'
    _pending.clear()
    _pending.update({'to': names[0], 'text': text, 'time': time.time(), 'others': names[1:]})
    others = f'（其它相近的：{"、".join(names[1:])}，说“发给 名字”换人）' if len(names) > 1 else ''
    return f'微信里没有叫“{to}”的人。你是不是想发给“{names[0]}”？说“确认”就发：{text}{others}'


def _click(x: float, y: float) -> None:
    import Quartz
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.05)


def send(to: str, text: str) -> str:
    """Open the chat with `to`, check its title, send `text`, check it appears. Returns a reply for the user."""
    saved = _clipboard()
    try:
        _osa('tell application "WeChat" to activate')
        time.sleep(0.6)
        _main_window()
        popup, rows = _search(to)
        exact = [r for r in rows if _norm(r['text']) == _norm(to)]
        if popup is None or not exact:
            _keys('key code 53')
            return f'没有发送：微信搜索里没找到名字正好是“{to}”的联系人或群。'
        hit = exact[0]
        _click(popup['x'] + (hit['x'] + hit['w'] / 2) / popup['scale'],
               popup['y'] + (hit['y'] + hit['h'] / 2) / popup['scale'])
        time.sleep(1.2)
        title, before = _read_pane()
        if _norm(title) != _norm(to):
            _keys('key code 53')                      # Escape: leave the search, type nothing
            return f'没有发送：搜索“{to}”打开的是“{title or '（没认出）'}”，和收件人对不上。'
        _set_clipboard(text)
        _keys('keystroke "v" using command down', 'delay 0.4', 'key code 36')
        time.sleep(1.5)
        _, after = _read_pane()
        # Sent = one more bubble with this text than before (a short chat shows new bubbles near the top).
        if _count(after, text) > _count(before, text):
            return f'已发给 {title}：{text}'
        return f'已在和 {title} 的聊天里按了发送，但截图里没认出这条消息，请看一眼微信确认。'
    except Exception as exc:
        return f'没能发微信：{exc}'
    finally:
        _set_clipboard(saved)


def parse(text: str) -> tuple[str, str] | None:
    match = ASK.search(str(text or '').strip())
    if not match:
        return None
    to = (match.group('to') or match.group('to2') or '').strip()
    body = (match.group('text') or match.group('text2') or '').strip().strip('“”"')
    return (to, body) if to and body else None


def answer(text: str) -> str | None:
    """Fast path: "微信给X发：…" (send now if X is pre-approved, else ask), then "确认"/"取消"."""
    text = str(text or '').strip()
    if _pending and time.time() - _pending['time'] < 300:
        if CONFIRM.match(text):
            pending = dict(_pending)
            _pending.clear()
            return send(pending['to'], pending['text'])
        switch = re.match(r'^(?:发给|是|给)\s*(.+?)[。.!！]?$', text)
        if switch and _norm(switch.group(1)) in {_norm(n) for n in _pending.get('others', [])}:
            _pending['to'] = switch.group(1).strip()
            _pending['others'] = []
            return f"好，改成发给“{_pending['to']}”：{_pending['text']}\n说“确认”发送。"
        if CANCEL.match(text):
            _pending.clear()
            return '好，不发了。'
    request = parse(text)
    if request is None:
        return None
    to, body = request
    try:
        exists, similar = lookup(to)
    except Exception as exc:
        return f'没能打开微信搜索：{exc}'
    if not exists:
        return _not_found(to, body, similar)
    if _norm(to) in {_norm(n) for n in SEND_WITHOUT_ASKING}:
        return send(to, body)
    _pending.clear()
    _pending.update({'to': to, 'text': body, 'time': time.time()})
    return f'要用微信发给“{to}”：{body}\n说“确认”发送，说“取消”不发。'

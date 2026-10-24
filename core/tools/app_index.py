"""D1: resolve what the user calls an app ("微信", "vscode", "谷歌浏览器") to the installed application.

`open -a 微信` fails because the bundle is WeChat.app, and the old open_app reported success anyway. The index
holds, for every installed .app, its file name, its localized display name (Spotlight's kMDItemDisplayName,
which follows the user's language: 微信, 计算器, 飞书), its English display name, its bundle id and a few curated
aliases. Resolution: exact name or alias -> unique substring -> close fuzzy match; several candidates are
returned instead of guessing.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOTS = ('/Applications', '/System/Applications', '/System/Applications/Utilities', '~/Applications',
         '/System/Library/CoreServices/Finder.app')
CACHE = Path('~/.kage/app-index.json').expanduser()
CACHE_TTL_S = 24 * 3600
# What people call apps that neither name covers (bundle id -> extra names). The pre-May open_app had a short
# alias table (微信, 网易云, 浏览器, 设置, 终端) that the 4db1b79 refactor dropped; these restore and extend it.
ALIASES = {
    'com.microsoft.VSCode': ['vscode', 'vs code', 'code'],
    'com.google.Chrome': ['chrome', '谷歌浏览器', '谷歌'],
    'com.netease.163music': ['网易云', '网易云音乐', 'neteasemusic'],
    'com.electron.lark': ['lark', '飞书'],
    'com.tencent.xinWeChat': ['wechat', '微信', 'weixin'],
    'com.apple.systempreferences': ['设置', '系统偏好设置', '偏好设置', 'settings', 'system preferences'],
    'com.apple.Terminal': ['终端', '命令行'],
    'com.apple.finder': ['访达', 'finder', '文件管理器'],
    'com.apple.ActivityMonitor': ['任务管理器', '活动监视器'],
    'com.apple.mail': ['邮件', '邮箱', 'mail'],
    'com.apple.iCal': ['日历', 'calendar'],
    'com.apple.reminders': ['提醒事项', '提醒'],
    'com.apple.Notes': ['备忘录', '笔记', 'notes'],
}
SUFFIXES = ('应用程序', '应用', '软件', '客户端', 'app', '.app')


def normalize(name: str) -> str:
    text = re.sub(r'\s+', ' ', str(name or '').strip().lower())
    for suffix in SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _app_paths() -> list[str]:
    paths = []
    for root in ROOTS:
        root = os.path.expanduser(root)
        if root.endswith('.app'):
            if os.path.isdir(root):
                paths.append(root)
        elif os.path.isdir(root):
            paths += [os.path.join(root, n) for n in sorted(os.listdir(root)) if n.endswith('.app')]
    return paths


def build_index() -> list[dict]:
    paths = _app_paths()
    # One mdls call for all apps: localized display name and bundle id (Spotlight follows the user's language).
    out = subprocess.run(['mdls', '-name', 'kMDItemDisplayName', '-name', 'kMDItemCFBundleIdentifier', *paths],
                         capture_output=True, text=True, timeout=30).stdout
    values = re.findall(r'^(kMDItem\w+)\s*=\s*(.*)$', out, flags=re.M)
    index = []
    for i, path in enumerate(paths):
        fields = dict(values[2 * i: 2 * i + 2]) if len(values) >= 2 * i + 2 else {}
        clean = lambda v: '' if v in (None, '(null)') else v.strip().strip('"')
        display = clean(fields.get('kMDItemDisplayName')).removesuffix('.app')
        bundle = clean(fields.get('kMDItemCFBundleIdentifier'))
        stem = Path(path).stem
        names = {normalize(n) for n in (stem, display, *ALIASES.get(bundle, [])) if n}
        index.append({'path': path, 'name': stem, 'display': display or stem, 'bundle_id': bundle,
                      'names': sorted(names)})
    return index


def load_index(refresh: bool = False) -> list[dict]:
    try:
        if not refresh and time.time() - CACHE.stat().st_mtime < CACHE_TTL_S:
            return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        pass
    index = build_index()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(index, ensure_ascii=False))
    return index


BROWSER_WORDS = ('浏览器', '默认浏览器', 'browser', 'web browser')


def default_browser() -> str:
    """Path of the app that opens http links (the user's default browser)."""
    import AppKit
    url = AppKit.NSWorkspace.sharedWorkspace().URLForApplicationToOpenURL_(AppKit.NSURL.URLWithString_('https://a.b'))
    return str(url.path()) if url else ''


def resolve(query: str, index: list[dict] | None = None) -> tuple[str, list[dict]]:
    """('ok', [app]) | ('ambiguous', candidates) | ('missing', suggestions)."""
    index = index if index is not None else load_index()
    q = normalize(query)
    if not q:
        return 'missing', []
    if q in BROWSER_WORDS:                       # "浏览器" means whatever the user browses with, not a fixed app
        try:
            path = default_browser()
        except Exception:
            path = ''
        match = [a for a in index if a['path'] == path]
        if match:
            return 'ok', match
    exact = [a for a in index if q in a['names']]
    if exact:
        return ('ok', exact[:1]) if len({a['bundle_id'] or a['path'] for a in exact}) == 1 else ('ambiguous', exact)
    def contains(n):               # "网易uu远程" ⊃ "uu远程"; Latin names only as whole words ("photoshop" ⊅ "photos")
        if n.isascii():
            return n in q.split() or (q in n and len(q) >= 2)
        return q in n or (len(n) >= 2 and n in q)
    partial = [a for a in index if any(contains(n) for n in a['names'])]
    if len(partial) == 1:
        return 'ok', partial
    def closeness(names):          # typos only: "photoshop" must not match "photos" (lengths differ by 3)
        return max([difflib.SequenceMatcher(None, q, n).ratio() for n in names if abs(len(n) - len(q)) <= 2] or [0])
    scored = sorted(((closeness(a['names']), a) for a in index), key=lambda x: -x[0])
    if partial:
        return 'ambiguous', partial[:5]
    if scored and scored[0][0] >= 0.8 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.1):
        return 'ok', [scored[0][1]]
    return 'missing', [a for s, a in scored[:3] if s >= 0.5]


_OPEN_PATTERNS = (
    re.compile(r'^(?:请|麻烦)?(?:你)?(?:帮我|给我)?(?:打开|启动|开一下|开下|运行)(?:一下)?\s*(?P<app>.+?)\s*(?:吧|呗|一下)?[。.!！]*$'),
    re.compile(r'^(?:请|麻烦)?(?:你)?(?:帮我|给我)?把\s*(?P<app>.+?)\s*(?:给我)?(?:打开|启动)(?:一下)?[。.!！]*$'),
    re.compile(r'^(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?(?P<app>.+?)(?:\s+app)?[.!]*$', re.I),
)
_NOT_AN_APP = ('网页', '网站', '文件', '文档', '链接', 'http', '.com', '.txt', '.md', '/')


def parse_open_request(text: str) -> str | None:
    """The app name in a plain "打开微信" / "把日历打开" / "open Safari" request, or None.

    D1: the 4B model claimed "已打开备忘录" with no tool call for 5 of 9 such requests, so these go to a server
    fast path (like undo) instead of the model. Anything that looks like a web page or a file stays with the model."""
    text = str(text or '').strip()
    if not text or len(text) > 40 or any(k in text.lower() for k in _NOT_AN_APP):
        return None
    for pattern in _OPEN_PATTERNS:
        match = pattern.match(text)
        app = match.group('app').strip() if match else ''
        # Compound requests ("打开微信然后给张三发消息…") are not a plain open: leave them to the model.
        if app and len(app) <= 20 and not re.search(r'[，,。；;]|然后|并且|再|之后|给.+发', app):
            return app
    return None


def open_app_reply(text: str) -> str | None:
    """The spoken reply for a fast-path open request (None: not one — let the model handle it)."""
    name = parse_open_request(text)
    if name is None:
        return None
    status, apps = resolve(name)
    if status == 'missing' and not apps:
        return None                         # not an installed app ("打开灯"?): the model decides
    result = open_app(name)
    if result.get('success'):
        return f"已打开{result['opened']}。"
    return result.get('message') or '没能打开这个应用。'


def open_app(app_name: str) -> dict:
    status, apps = resolve(app_name)
    if status == 'missing' and apps == []:
        status, apps = resolve(app_name, load_index(refresh=True))   # maybe installed since the cache was built
    if status != 'ok':
        names = [a['display'] for a in apps]
        message = (f'有多个可能的应用：{"、".join(names)}，请说具体是哪一个' if status == 'ambiguous'
                   else f'没有找到叫“{app_name}”的应用' + (f'，是不是：{"、".join(names)}？' if names else ''))
        return {'success': False, 'error': 'Ambiguous' if status == 'ambiguous' else 'NotFound',
                'message': message, 'candidates': names}
    app = apps[0]
    if os.environ.get('KAGE_OPEN_APP_DRY_RUN') == '1':                  # tests: resolve only, do not launch
        return {'success': True, 'opened': app['display'], 'path': app['path'], 'dry_run': True}
    result = subprocess.run(['open', app['path']], capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        return {'success': False, 'error': 'OpenFailed', 'message': (result.stderr or '').strip()[:300]}
    return {'success': True, 'opened': app['display'], 'path': app['path']}

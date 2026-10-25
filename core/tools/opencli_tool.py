"""D5: websites through OpenCLI (jackwener/opencli; npm global, Chrome Browser Bridge extension).

OpenCLI turns sites into JSON commands that run in the user's logged-in Chrome. Kage exposes:
- `opencli_read(site, command, args)`: only commands the catalog marks `access: read`;
- `opencli_write(...)`: write commands (comment, follow, publish…) — DANGEROUS, so the server asks the user first.
The 4B model cannot pick from 1,289 commands, so the server attaches the named site's read commands (name,
purpose, arguments) to the request (`site_hint`), the same "give it the information" fix as D0's paths.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import time

CACHE = Path('~/.kage/opencli-catalog.json').expanduser()
CACHE_TTL_S = 7 * 24 * 3600
SITES = {  # what people say -> OpenCLI site
    'b站': 'bilibili', '哔哩哔哩': 'bilibili', 'bilibili': 'bilibili', '知乎': 'zhihu', 'zhihu': 'zhihu',
    '小红书': 'xiaohongshu', 'xiaohongshu': 'xiaohongshu', '微博': 'weibo', 'weibo': 'weibo', '抖音': 'douyin',
    'douyin': 'douyin', '12306': '12306', '一亩三分地': '1point3acres', '微信读书': 'weread', '闲鱼': 'xianyu',
    'hacker news': 'hackernews', 'hackernews': 'hackernews', 'reddit': 'reddit', 'github': 'github',
}
MAX_ROWS, MAX_FIELD = 10, 300
# "read" in OpenCLI means "does not change the account"; these still act on the machine or need a session flow.
NOT_FOR_READ_TOOL = {'download', 'login', 'whoami'}


def binary() -> str:
    found = shutil.which('opencli')
    if found:
        return found
    for candidate in sorted(Path('~/.nvm/versions/node').expanduser().glob('*/bin/opencli'), reverse=True):
        return str(candidate)                    # the app may run without the shell's nvm PATH
    raise RuntimeError('opencli is not installed (npm install -g @jackwener/opencli)')


def _run(args: list[str], timeout: float = 150) -> dict:
    result = subprocess.run([binary(), *args, '-f', 'json'], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(result.stdout or '{}')
    except ValueError:
        return {'ok': False, 'error': {'code': 'BadOutput', 'message': (result.stderr or result.stdout)[:300]}}


def catalog(site: str) -> list[dict]:
    """[{name, access, description, positionals, options}] for one site (cached a week)."""
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cached = {}
    entry = cached.get(site)
    if entry and time.time() - entry['time'] < CACHE_TTL_S:
        return entry['commands']
    listed = _run(['list', '--site', site, '--limit', '100'], timeout=60)
    commands = []
    for row in (listed.get('data') or {}).get('commands', []):
        name = row['command'].split(' ', 1)[1]
        detail = _run([site, *name.split(' '), '--help'], timeout=30)
        positionals = [p.get('name') for p in detail.get('positionals', [])] if 'positionals' in detail else []
        options = [o.get('name') for o in detail.get('command_options', [])] if 'command_options' in detail else []
        commands.append({'name': name, 'access': row.get('access', 'write'), 'description': row.get('description', ''),
                         'positionals': positionals, 'options': options})
    cached[site] = {'time': time.time(), 'commands': commands}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cached, ensure_ascii=False))
    return commands


def site_of(text: str) -> str | None:
    low = str(text or '').lower()
    for word, site in ((w, SITES[w]) for w in ROUTED):
        if word in low:
            return site
    return None


def site_hint(text: str) -> str:
    site = site_of(text)
    if site is None:
        return ''
    try:
        reads = [c for c in catalog(site) if c['access'] == 'read' and c['name'] not in NOT_FOR_READ_TOOL]
    except Exception:
        return ''
    if not reads:
        return ''
    listing = '；'.join(
        f"{c['name']}（{c['description'][:24]}" + (f"，参数 {'、'.join(c['positionals'])}" if c['positionals'] else '')
        + (f"，选项 {'、'.join(o for o in c['options'] if o in ('limit', 'sort', 'type'))}" if any(o in ('limit', 'sort', 'type') for o in c['options']) else '')
        + '）' for c in reads[:24])
    return (f"\n[系统：网站 {site} 可用的只读命令：{listing}。用 opencli_read(site=\"{site}\", command=命令名, "
            'args={参数名: 值}) 获取结果，再据此回答；搜索词用用户的原话，不要改写；不要编造结果。]')


def _trim(value):
    if isinstance(value, str):
        return value if len(value) <= MAX_FIELD else value[:MAX_FIELD] + '…'
    if isinstance(value, list):
        return [_trim(v) for v in value[:MAX_ROWS]]
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    return value


def _argv(site: str, spec: dict, args: dict | None) -> list[str]:
    args = dict(args or {})
    argv = [site, *spec['name'].split(' ')]
    for name in spec['positionals']:
        if name in args:
            argv.append(str(args.pop(name)))
    if 'limit' in spec['options'] and 'limit' not in args:
        args['limit'] = MAX_ROWS
    for name, value in args.items():
        if name in spec['options']:
            argv += [f'--{name}', str(value)]
    return argv


def _lookup(site: str, command: str) -> dict | None:
    site = SITES.get(str(site).lower(), str(site).lower())
    return next((c for c in catalog(site) if c['name'] == str(command).strip()), None)


def opencli_read(site: str, command: str, args: dict | None = None) -> str:
    site = SITES.get(str(site).lower(), str(site).lower())
    try:
        spec = _lookup(site, command)
    except Exception as exc:
        return json.dumps({'success': False, 'error': 'OpenCLIUnavailable', 'message': str(exc)}, ensure_ascii=False)
    if spec is None:
        return json.dumps({'success': False, 'error': 'UnknownCommand',
                           'message': f'{site} 没有命令 {command}；可用的见请求里的命令列表'}, ensure_ascii=False)
    if spec['access'] != 'read' or spec['name'] in NOT_FOR_READ_TOOL:
        return json.dumps({'success': False, 'error': 'WriteCommand',
                           'message': f'{site} {command} 会改动你的账号（{spec["access"]}），要用 opencli_write 并经用户确认'},
                          ensure_ascii=False)
    result = _run(_argv(site, spec, args))
    if not result.get('ok'):
        error = result.get('error') or {}
        message = error.get('message', '')
        if error.get('code') == 'AUTH_REQUIRED':
            message = f'需要先在 Chrome 里登录 {site}（{error.get("hint", "")}）'
        return json.dumps({'success': False, 'error': error.get('code', 'Failed'), 'message': message[:300]}, ensure_ascii=False)
    data = result.get('data')
    if data in (None, [], {}):              # anonymous sessions often get an empty page instead of an error
        return json.dumps({'success': False, 'error': 'EmptyResult',
                           'message': f'没有拿到数据；如果你还没在 Chrome 里登录 {site}，请先登录再试'}, ensure_ascii=False)
    return json.dumps({'success': True, 'site': site, 'command': command, 'data': _trim(data)}, ensure_ascii=False)


def opencli_write(site: str, command: str, args: dict | None = None) -> str:
    """Runs only after the user confirmed (registered DANGEROUS)."""
    site = SITES.get(str(site).lower(), str(site).lower())
    spec = _lookup(site, command)
    if spec is None:
        return json.dumps({'success': False, 'error': 'UnknownCommand', 'message': f'{site} 没有命令 {command}'}, ensure_ascii=False)
    result = _run(_argv(site, spec, args))
    return json.dumps({'success': bool(result.get('ok')), 'data': _trim(result.get('data')),
                       'error': (result.get('error') or {}).get('message')}, ensure_ascii=False)


SITE_SYSTEM = ('你是 Kage，用户的电脑助手。用户问的是某个网站上的内容。先调用 opencli_read 拿到真实数据，再用中文简洁回答'
               '（列表最多 5 条，带上标题和作者等关键信息）。搜索词用用户原话。工具失败时如实说明原因（例如需要先在 Chrome '
               '登录），不要编造。')


def answer_with_site(model, text: str, max_steps: int = 3) -> str | None:
    """A small dedicated loop for "B站热门 / 知乎热榜 / 小红书搜…": one tool (opencli_read), the site's command list,
    the local model. Runs before Kage's older video/search heuristics, which grabbed these requests in the first
    end-to-end test (a YouTube search, a web search answering "知乎热榜" with Zhihu's own homepage blurb)."""
    hint = site_hint(text)
    if not hint:
        return None
    tool = {'type': 'function', 'function': {'name': 'opencli_read', 'description': '读取网站内容（只读）',
            'parameters': {'type': 'object', 'properties': {
                'site': {'type': 'string'}, 'command': {'type': 'string'}, 'args': {'type': 'object'}},
                'required': ['site', 'command']}}}
    messages = [{'role': 'system', 'content': SITE_SYSTEM}, {'role': 'user', 'content': str(text) + hint}]
    for step in range(max_steps):
        response = model.generate(messages=messages, tools=[tool], max_tokens=600, temperature=0.3)
        calls = list(getattr(response, 'tool_calls', None) or [])
        if not calls:
            return str(getattr(response, 'text', '') or '').strip() or None
        call = calls[0]
        result = opencli_read(**{k: v for k, v in (call.get('arguments') or {}).items() if k in ('site', 'command', 'args')})
        call_id = f'call_{step}'
        messages += [{'role': 'assistant', 'content': getattr(response, 'text', '') or '',
                      'tool_calls': [{'id': call_id, 'type': 'function', 'function': {
                          'name': 'opencli_read', 'arguments': json.dumps(call.get('arguments') or {}, ensure_ascii=False)}}]},
                     {'role': 'tool', 'tool_call_id': call_id, 'content': result[:6000]}]
    final = model.generate(messages=messages + [{'role': 'user', 'content': '根据上面的结果直接回答。'}], max_tokens=600,
                           temperature=0.3)
    return str(getattr(final, 'text', '') or '').strip() or None


def register(registry) -> None:
    from core.tool_registry import ToolDefinition
    schema = {'type': 'object', 'properties': {
        'site': {'type': 'string', 'description': '网站，如 bilibili、zhihu、xiaohongshu'},
        'command': {'type': 'string', 'description': '命令名，见请求里附的命令列表'},
        'args': {'type': 'object', 'description': '参数，如 {"query": "咖啡", "limit": 5}', 'default': {}}},
        'required': ['site', 'command']}
    registry.register(ToolDefinition(
        name='opencli_read', description='读取网站内容（B站、知乎、小红书等，用你 Chrome 里已登录的账号，只读）。',
        parameters=schema, handler=opencli_read, safety_level='SAFE'))
    registry.register(ToolDefinition(
        name='opencli_write', description='在网站上执行会改动账号的操作（评论、关注、发布等），执行前必须经用户确认。',
        parameters=schema, handler=opencli_write, safety_level='DANGEROUS'))


# Routing (tool narrowing + command hints) only for sites named unambiguously; "github" appears in ordinary coding
# requests and must not take the tools away from them.
ROUTED = [k for k, site in SITES.items() if site not in ('github', 'reddit', 'hackernews')]
SITE_PATTERN = re.compile('|'.join(re.escape(k) for k in ROUTED), re.I)

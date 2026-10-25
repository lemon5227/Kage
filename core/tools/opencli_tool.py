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
# Login pages Kage opens when a site needs the user to sign in (user request 10-25). Kage never types or stores
# passwords: Chrome's own password manager fills saved ones, otherwise the user types them.
LOGIN_URLS = {'zhihu': 'https://www.zhihu.com/signin', 'xiaohongshu': 'https://www.xiaohongshu.com',
              'bilibili': 'https://passport.bilibili.com/login', 'weibo': 'https://weibo.com/login.php',
              'douyin': 'https://www.douyin.com', 'weread': 'https://weread.qq.com', 'xianyu': 'https://www.goofish.com',
              '12306': 'https://kyfw.12306.cn/otn/resources/login.html', '1point3acres': 'https://www.1point3acres.com/bbs/'}
RESUME = re.compile(r'^(我)?(已经)?(登录|登陆)(好|完)?(了)?[。.!！]?$|^(好了|登好了|登录好了|登陆好了)[。.!！]?$')
_pending: dict = {}           # {'site', 'text', 'time'}: a request waiting for the user to log in
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


# Public lists change slowly: reuse a result for a few minutes instead of driving Chrome again (~4 s each).
# Account-specific reads (feed, notifications, profile…) are never cached. Rows are fetched at MAX_ROWS so
# "前三" and "前五" share one entry.
RESULT_TTL_S = {'hot': 300, 'ranking': 300, 'trending': 300, 'latest': 300, 'news': 300, 'search': 1800}
RESULT_CACHE = Path('~/.kage/cache/opencli-results.json').expanduser()
REFRESH = re.compile(r'刷新|最新的|重新(获取|查|看)')


def _cache_load() -> dict:
    try:
        return json.loads(RESULT_CACHE.read_text())
    except (OSError, ValueError):
        return {}


RESULT_CACHE_MAX = 200        # entries; beyond it the least recently used go first (expired ones always go)


def _cache_save(cache: dict) -> None:
    try:
        RESULT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    except OSError:
        pass


def _cache_store(key: str, data) -> None:
    """Expiry first (lists go stale), then LRU when over RESULT_CACHE_MAX (many distinct searches)."""
    now = time.time()
    cache = {k: v for k, v in _cache_load().items() if now - v['time'] < max(RESULT_TTL_S.values())}
    cache[key] = {'time': now, 'used': now, 'data': data}
    if len(cache) > RESULT_CACHE_MAX:
        keep = sorted(cache, key=lambda k: cache[k].get('used', cache[k]['time']), reverse=True)[:RESULT_CACHE_MAX]
        cache = {k: cache[k] for k in keep}
    _cache_save(cache)


def _cache_get(key: str, ttl: float):
    cache = _cache_load()
    hit = cache.get(key)
    if not hit or time.time() - hit['time'] >= ttl:
        return None
    hit['used'] = time.time()                 # recency for LRU, not freshness: 'time' stays the fetch time
    _cache_save(cache)
    return hit


def opencli_read(site: str, command: str, args: dict | None = None, fresh: bool = False) -> str:
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
    ttl = RESULT_TTL_S.get(spec['name'], 0)
    if ttl:
        args = {**(args or {}), 'limit': MAX_ROWS}
    argv = _argv(site, spec, args)
    key = ' '.join(argv)
    if ttl and not fresh:
        hit = _cache_get(key, ttl)
        if hit:
            return json.dumps({'success': True, 'site': site, 'command': command, 'data': hit['data'],
                               'cached_age_s': int(time.time() - hit['time'])}, ensure_ascii=False)
    result = _run(argv)
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
    data = _trim(data)
    if ttl:
        _cache_store(key, data)
    return json.dumps({'success': True, 'site': site, 'command': command, 'data': data}, ensure_ascii=False)


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


TITLE_FIELDS = ('title', 'name', 'word', 'keyword', 'question', 'desc', 'text')
METRIC_FIELDS = ('heat', 'hot', 'hot_value', 'score', 'play', 'views', 'view', 'likes', 'votes', 'answers')
AUTHOR_FIELDS = ('author', 'owner', 'up', 'user')
COUNTS = {'1': '只要第一名 / 一条', '3': '前三条', '5': '没说数量，或前五条', '10': '前十条或更多'}
CONFIDENT = 0.8
STOP_WORDS = re.compile(r'(请|帮我|给我|关于|有没有讲|有没有|讲|介绍|相关|在|去|到|上面?|里面?|一下|看看|搜一搜|搜索|搜|查一下|查查|查|找一下|找找|找|'
                        r'有哪些|有什么|是什么|是哪些|是哪个|都有啥|吗|呢|的?热门|热榜|热搜|内容|视频|问题|帖子|笔记|[？?。！!，,])')


DISPLAY = {'bilibili': 'B站'}


def display_name(site: str) -> str:
    return DISPLAY.get(site) or next((k for k, v in SITES.items() if v == site and not k.isascii()), site)


def _rows_text(rows: list, with_author: bool) -> list[str]:
    lines = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            lines.append(f'{i}. {row}')
            continue
        title = re.sub(r'</?em>', '', next((str(row[f]) for f in TITLE_FIELDS if row.get(f)), ''))
        if not title:
            continue
        metric = next((f'{row[f]}' for f in METRIC_FIELDS if row.get(f) not in (None, '')), '')
        author = re.sub(r'</?em>', '', next((str(row[f]) for f in AUTHOR_FIELDS if row.get(f)), '')) if with_author else ''
        lines.append(f'{i}. {title}' + (f'（{metric}）' if metric else '') + (f' — {author}' if author else ''))
    return lines


def query_candidates(text: str) -> list[str]:
    """Possible search terms cut from the user's words (the decision model picks one; it cannot write text)."""
    text = re.sub('|'.join(re.escape(k) for k in ROUTED), ' ', str(text or ''), flags=re.I)
    found = [m for m in re.findall(r'[“"「](.+?)[”"」]', text)]          # quoted words are the search term
    about = re.search(r'关于\s*(.+?)\s*的', text)
    if about:
        found.append(about.group(1))
    after = re.search(r'(?:搜一下|搜一搜|搜索|搜|查一下|查|找一下|找)\s*[：:]?\s*(.+)$', text)
    if after:
        found.append(STOP_WORDS.sub(' ', after.group(1)))
    found.append(STOP_WORDS.sub(' ', text))
    out = []
    for q in found:
        q = re.sub(r'\s+', ' ', q).strip(' 的“”"「」')
        if q and q not in out and len(q) <= 30:
            out.append(q)
    return out


def decide(text: str, site: str, reads: dict) -> dict | None:
    """Ask the decision model which read command fits, whether a plain list answers the request, how many rows,
    and (for a search) which search term. None when it is unavailable."""
    from core import decision_model
    if not decision_model.available():
        return None
    commands = {name: (c['description'] or name)[:60] for name, c in reads.items()
                if name not in NOT_FOR_READ_TOOL and name not in ('whoami', 'me')}
    commands['none'] = '以上命令都不合适'
    questions = {
        'command': {'type': 'choice', 'question': f'要满足这个请求，应该运行网站 {site} 的哪个只读命令？',
                    'criteria': commands},
        # asked as a concrete item, not "is a list enough?" (whole-request judgements were Clef's weak spot: 0.64)
        'needs_reading': {'type': 'noul', 'question': '用户是否要求对条目做总结、解释、比较、挑出最高/最低，或按某个条件筛选？'},
        'count': {'type': 'choice', 'question': '用户想看几条？', 'criteria': COUNTS},
    }
    queries = query_candidates(text)
    if queries:
        questions['query'] = {'type': 'choice', 'question': '如果要搜索，最合适的搜索词是哪个？',
                              'criteria': {**{f'q{i}': q for i, q in enumerate(queries)}, 'none': '都不合适'}}
    try:
        answers = decision_model.ask(f'用户对桌面助手说：{text}', questions, run_id='site-route')
    except decision_model.DecisionUnavailable:
        return None
    query = answers.get('query', (None, 0.0, {}))
    return {'command': answers['command'][0], 'command_conf': answers['command'][1],
            'list_only': not answers['needs_reading'][0], 'list_conf': answers['needs_reading'][1],
            'count': int(answers['count'][0] or 5),
            'query': queries[int(query[0][1:])] if query[0] and query[0] != 'none' else None, 'query_conf': query[1],
            'latency_s': answers['_latency_s']}


LAST_DECISION: dict = {}      # for the usage log / tests: what decided the last site request


def quick_answer(text: str) -> str | None:
    """Site requests the decision model is sure about: it picks the command (and search term, row count), the
    program runs it and lists the rows. Replaces the local model's command choice (~4 s) and retelling (~6 s);
    14 s → ~5 s for "知乎热榜前三" (10-25). None: not confident, or the request needs reading the content →
    the local model's loop handles it. (A regex version tried first got 2 of 7 phrasings wrong.)"""
    LAST_DECISION.clear()
    site = site_of(text)
    if site is None:
        return None
    try:
        reads = {c['name']: c for c in catalog(site) if c['access'] == 'read'}
    except Exception:
        return None
    decision = decide(str(text), site, reads)
    if decision is None:
        return None
    LAST_DECISION.update(decision, site=site, by='clef')
    command = decision['command']
    if (command not in reads or decision['command_conf'] < CONFIDENT or not decision['list_only']
            or decision['list_conf'] < CONFIDENT):
        LAST_DECISION['by'] = 'local-model'
        return None
    args, head = {'limit': max(decision['count'], 1)}, ''
    if reads[command]['positionals']:
        if not decision['query'] or decision['query_conf'] < CONFIDENT:
            LAST_DECISION['by'] = 'local-model'
            return None
        args[reads[command]['positionals'][0]] = decision['query']
        head = f'“{decision["query"]}”'
    result = json.loads(opencli_read(site, command, args, fresh=bool(REFRESH.search(str(text)))))
    if not result.get('success'):
        if result.get('error') in ('AUTH_REQUIRED', 'EmptyResult'):
            return open_login(site, text)
        LAST_DECISION['by'] = 'local-model'
        return None
    _last_site_request.update(text=str(text).removesuffix('（刷新）'), time=time.time())
    rows = result['data'] if isinstance(result['data'], list) else [result['data']]
    lines = _rows_text(rows[:decision['count']], with_author=bool(head))
    if not lines:
        return None
    name = display_name(site)
    if head:
        title = f'{name}搜索{head}的前 {len(lines)} 条：'
    else:
        what = re.split(r'[\s(（,，]', reads[command]['description'] or '')[0][:16]
        if not what or what.isascii():
            what = {'hot': '热门', 'ranking': '排行榜', 'feed': '推荐', 'latest': '最新'}.get(command, command)
        title = f'{what if what.startswith(name) else name + what}前 {len(lines)} 条：'
    age = result.get('cached_age_s')
    note = f'\n（{max(age // 60, 1)} 分钟前取的，说“刷新”重新获取）' if age and age >= 30 else ''
    return title + '\n' + '\n'.join(lines) + note


_last_site_request: dict = {}


def refresh_last(text: str) -> str | None:
    """"刷新" right after a site answer (within 30 min): fetch the same request again, skipping the cache."""
    if not re.fullmatch(r'\s*(刷新|刷新一下|再刷新一下|重新获取)[。.!！]?\s*', str(text or '')) or not _last_site_request:
        return None
    if time.time() - _last_site_request['time'] > 1800:
        return None
    return quick_answer(_last_site_request['text'] + '（刷新）')


def answer_with_site(model, text: str, max_steps: int = 3) -> str | None:
    """A small dedicated loop for "B站热门 / 知乎热榜 / 小红书搜…": one tool (opencli_read), the site's command list,
    the local model. Runs before Kage's older video/search heuristics, which grabbed these requests in the first
    end-to-end test (a YouTube search, a web search answering "知乎热榜" with Zhihu's own homepage blurb)."""
    quick = quick_answer(text)
    if quick:
        return quick
    hint = site_hint(text)
    if not hint:
        return None
    tool = {'type': 'function', 'function': {'name': 'opencli_read', 'description': '读取网站内容（只读）',
            'parameters': {'type': 'object', 'properties': {
                'site': {'type': 'string'}, 'command': {'type': 'string'}, 'args': {'type': 'object'}},
                'required': ['site', 'command']}}}
    messages = [{'role': 'system', 'content': SITE_SYSTEM}, {'role': 'user', 'content': str(text) + hint}]
    login_site = None
    for step in range(max_steps):
        response = model.generate(messages=messages, tools=[tool], max_tokens=600, temperature=0.3)
        calls = list(getattr(response, 'tool_calls', None) or [])
        if not calls:
            return str(getattr(response, 'text', '') or '').strip() or None
        call = calls[0]
        result = opencli_read(**{k: v for k, v in (call.get('arguments') or {}).items() if k in ('site', 'command', 'args')})
        try:
            parsed = json.loads(result)
        except ValueError:
            parsed = {}
        if parsed.get('error') in ('AUTH_REQUIRED', 'EmptyResult'):
            login_site = SITES.get(str((call.get('arguments') or {}).get('site', '')).lower(),
                                   str((call.get('arguments') or {}).get('site', '')).lower())
            break
        call_id = f'call_{step}'
        messages += [{'role': 'assistant', 'content': getattr(response, 'text', '') or '',
                      'tool_calls': [{'id': call_id, 'type': 'function', 'function': {
                          'name': 'opencli_read', 'arguments': json.dumps(call.get('arguments') or {}, ensure_ascii=False)}}]},
                     {'role': 'tool', 'tool_call_id': call_id, 'content': result[:6000]}]
    if login_site:
        return open_login(login_site, text)
    final = model.generate(messages=messages + [{'role': 'user', 'content': '根据上面的结果直接回答。'}], max_tokens=600,
                           temperature=0.3)
    return str(getattr(final, 'text', '') or '').strip() or None


def open_login(site: str, text: str) -> str:
    """Open the site's login page in Chrome and remember the request until the user says they are logged in."""
    url = LOGIN_URLS.get(site, f'https://www.{site}.com')
    name = display_name(site)
    again = _pending.get('site') == site and _pending.get('text') == str(text)
    try:
        subprocess.run(['open', '-a', 'Google Chrome', url], check=True, timeout=10)
    except Exception as exc:
        return f'{site} 需要先登录，但没能打开登录页（{exc}）。请在 Chrome 里打开 {url} 登录。'
    _pending.clear()
    _pending.update({'site': site, 'text': str(text), 'time': time.time()})
    if again:
        return f'{name} 看起来还是没登录（Chrome 里的登录页已重新打开）。登录成功后再跟我说“登录好了”。'
    return (f'{name} 还没登录，我已经在 Chrome 里打开了登录页（{url}）。Chrome 存过密码会自动填好，没存过请你自己输入；'
            '登录好了跟我说“登录好了”，我接着查。')


def resume_after_login(model, text: str) -> str | None:
    """"登录好了" within 15 minutes of a login prompt: run the remembered request again."""
    if not RESUME.match(str(text or '').strip()) or not _pending or time.time() - _pending['time'] > 900:
        return None
    pending = dict(_pending)
    reply = answer_with_site(model, pending['text'])      # still not logged in: open_login re-arms _pending
    if _pending.get('time') == pending['time']:
        _pending.clear()
    if not reply or '看起来还是没登录' in reply:
        return reply
    return f"好的，接着查“{pending['text']}”：\n{reply}"


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

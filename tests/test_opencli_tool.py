"""D5: OpenCLI wrapper — command lookup, argv building, read/write separation (no browser, no network)."""
import json

from core.tools import opencli_tool as oc

CATALOG = [
    {'name': 'hot', 'access': 'read', 'description': 'B站热门视频', 'positionals': [], 'options': ['limit']},
    {'name': 'search', 'access': 'read', 'description': '搜索', 'positionals': ['query'], 'options': ['limit', 'type']},
    {'name': 'comment', 'access': 'write', 'description': '发评论', 'positionals': ['bvid', 'message'], 'options': []},
    {'name': 'download', 'access': 'read', 'description': '下载视频', 'positionals': ['bvid'], 'options': []},
]


def test_argv_positionals_options_and_default_limit():
    assert oc._argv('bilibili', CATALOG[1], {'query': 'Agent 教程', 'type': 'video'}) == \
        ['bilibili', 'search', 'Agent 教程', '--type', 'video', '--limit', '10']
    assert oc._argv('bilibili', CATALOG[0], {'limit': 3, 'unknown': 1}) == ['bilibili', 'hot', '--limit', '3']


def test_read_tool_refuses_writes_and_downloads(monkeypatch):
    monkeypatch.setattr(oc, 'catalog', lambda site: CATALOG)
    calls = []
    monkeypatch.setattr(oc, '_run', lambda args, timeout=150: calls.append(args) or {'ok': True, 'data': [{'title': 'x' * 400}]})
    assert json.loads(oc.opencli_read('b站', 'comment', {}))['error'] == 'WriteCommand'
    assert json.loads(oc.opencli_read('bilibili', 'download', {'bvid': 'BV1'}))['error'] == 'WriteCommand'
    assert json.loads(oc.opencli_read('bilibili', 'nope'))['error'] == 'UnknownCommand'
    ok = json.loads(oc.opencli_read('哔哩哔哩', 'hot', {'limit': 2}))
    assert ok['success'] and len(ok['data'][0]['title']) == oc.MAX_FIELD + 1 and calls == [['bilibili', 'hot', '--limit', '2']]


def test_routing_words():
    assert oc.site_of('B站最近有什么热门') == 'bilibili' and oc.site_of('知乎热榜') == 'zhihu'
    assert oc.site_of('把代码推到 github') is None and not oc.SITE_PATTERN.search('把代码推到 github')


def test_empty_result_points_to_login(monkeypatch):
    monkeypatch.setattr(oc, 'catalog', lambda site: CATALOG)
    monkeypatch.setattr(oc, '_run', lambda args, timeout=150: {'ok': True, 'data': []})
    out = json.loads(oc.opencli_read('知乎', 'hot'))
    assert out['error'] == 'EmptyResult' and '登录' in out['message']


def test_named_site_skips_the_video_fast_path():
    from core.realtime_lane import classify_realtime_task
    assert classify_realtime_task('B站现在热门视频前五是什么').reason == 'opencli_site'
    assert classify_realtime_task('帮我找个 youtube 视频').reason == 'video_fastpath'


def test_login_flow_opens_page_and_resumes(monkeypatch):
    opened = []
    monkeypatch.setattr(oc.subprocess, 'run', lambda args, **kw: opened.append(args))
    monkeypatch.setattr(oc, 'site_hint', lambda text: '\n[hint]')

    class Model:
        def __init__(self):
            self.n = 0
        def generate(self, messages, tools=None, **kw):
            self.n += 1
            from types import SimpleNamespace
            return SimpleNamespace(text='', tool_calls=[{'name': 'opencli_read', 'arguments': {'site': 'zhihu', 'command': 'hot'}}])
    monkeypatch.setattr(oc, 'opencli_read', lambda **kw: json.dumps({'success': False, 'error': 'AUTH_REQUIRED'}))
    reply = oc.answer_with_site(Model(), '知乎热榜有什么')
    assert '已经在 Chrome 里打开了登录页' in reply and opened[-1][-1] == oc.LOGIN_URLS['zhihu']
    assert oc.resume_after_login(Model(), '今天天气') is None
    monkeypatch.setattr(oc, 'answer_with_site', lambda model, text: '热榜：……')
    assert oc.resume_after_login(Model(), '登录好了').endswith('热榜：……')
    assert oc.resume_after_login(Model(), '登录好了') is None              # only once


def test_login_flow_still_not_logged_in(monkeypatch):
    monkeypatch.setattr(oc.subprocess, 'run', lambda args, **kw: None)
    oc._pending.clear()
    first = oc.open_login('xiaohongshu', '小红书搜咖啡')
    assert first.startswith('小红书 还没登录')
    monkeypatch.setattr(oc, 'answer_with_site', lambda model, text: oc.open_login('xiaohongshu', text))
    again = oc.resume_after_login(None, '登录好了')
    assert '还是没登录' in again and oc._pending['text'] == '小红书搜咖啡'   # still waiting

"""D5: OpenCLI wrapper — command lookup, argv building, read/write separation (no browser, no network)."""
import json

from core.tools import opencli_tool as oc

CATALOG = [
    {'name': 'hot', 'access': 'read', 'description': 'B站热门视频', 'positionals': [], 'options': ['limit']},
    {'name': 'search', 'access': 'read', 'description': '搜索', 'positionals': ['query'], 'options': ['limit', 'type']},
    {'name': 'comment', 'access': 'write', 'description': '发评论', 'positionals': ['bvid', 'message'], 'options': []},
    {'name': 'download', 'access': 'read', 'description': '下载视频', 'positionals': ['bvid'], 'options': []},
]


import pytest


@pytest.fixture(autouse=True)
def _private_result_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, 'RESULT_CACHE', tmp_path / 'opencli-results.json')   # never the user's real cache


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
    assert ok['success'] and len(ok['data'][0]['title']) == oc.MAX_FIELD + 1 and calls == [['bilibili', 'hot', '--limit', str(oc.MAX_ROWS)]]   # lists cached at full length


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


def _fake_decision(monkeypatch, answers):
    from core import decision_model
    monkeypatch.setattr(decision_model, 'available', lambda: True)
    monkeypatch.setattr(decision_model, 'ask', lambda state, questions, **kw: {**answers, '_latency_s': 0.3})
    monkeypatch.setattr(oc, 'catalog', lambda site: [
        {'name': 'hot', 'access': 'read', 'description': '知乎热榜', 'positionals': [], 'options': ['limit']},
        {'name': 'search', 'access': 'read', 'description': '搜索', 'positionals': ['query'], 'options': ['limit']}])


def test_query_candidates():
    assert oc.query_candidates('在知乎搜一下大模型 Agent') == ['大模型 Agent']
    assert oc.query_candidates('知乎上关于考研的热门问题有哪些')[0] == '考研'
    assert oc.query_candidates('在知乎搜“考研数学怎么复习”')[0] == '考研数学怎么复习'


def test_confident_decision_lists_rows_without_the_model(monkeypatch):
    _fake_decision(monkeypatch, {'command': ('hot', 0.98, {}), 'needs_reading': (False, 0.95, {}),
                                 'count': ('3', 0.9, {}), 'query': ('none', 0.9, {})})
    calls = []
    monkeypatch.setattr(oc, 'opencli_read', lambda site, command, args=None, **kw: calls.append((command, args)) or json.dumps(
        {'success': True, 'data': [{'title': f't{i}', 'heat': f'{i} 万热度'} for i in range(10)]}))
    reply = oc.quick_answer('知乎热榜前三是什么')
    assert calls == [('hot', {'limit': 3})] and reply.startswith('知乎热榜前 3 条') and '3. t2（2 万热度）' in reply
    assert oc.LAST_DECISION['by'] == 'clef'


def test_search_uses_the_chosen_term(monkeypatch):
    _fake_decision(monkeypatch, {'command': ('search', 0.97, {}), 'needs_reading': (False, 0.95, {}),
                                 'count': ('5', 0.9, {}), 'query': ('q0', 0.99, {})})
    calls = []
    monkeypatch.setattr(oc, 'opencli_read', lambda site, command, args=None, **kw: calls.append(args) or json.dumps(
        {'success': True, 'data': [{'title': '<em>大模型</em> Agent 入门', 'votes': 9, 'author': 'a'}]}))
    reply = oc.quick_answer('在知乎搜一下大模型 Agent')
    assert calls == [{'limit': 5, 'query': '大模型 Agent'}] and '1. 大模型 Agent 入门（9） — a' in reply


def test_unsure_or_reading_requests_go_to_the_local_model(monkeypatch):
    monkeypatch.setattr(oc, 'opencli_read', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    _fake_decision(monkeypatch, {'command': ('hot', 0.95, {}), 'needs_reading': (True, 0.9, {}),
                                 'count': ('1', 0.9, {}), 'query': ('none', 0.9, {})})
    assert oc.quick_answer('知乎热榜第一条讲的是什么，帮我总结一下') is None and oc.LAST_DECISION['by'] == 'local-model'
    _fake_decision(monkeypatch, {'command': ('hot', 0.6, {}), 'needs_reading': (False, 0.9, {}),
                                 'count': ('5', 0.9, {}), 'query': ('none', 0.9, {})})
    assert oc.quick_answer('知乎现在大家在聊啥') is None


def test_public_lists_are_cached_and_refreshable(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, 'RESULT_CACHE', tmp_path / 'r.json')
    monkeypatch.setattr(oc, '_lookup', lambda site, command: {'name': command, 'access': 'read', 'positionals': [],
                                                              'options': ['limit']})
    runs = []
    monkeypatch.setattr(oc, '_run', lambda argv, **kw: runs.append(argv) or {'ok': True, 'data': [{'title': 'x'}]})
    first = json.loads(oc.opencli_read('zhihu', 'hot', {'limit': 3}))
    second = json.loads(oc.opencli_read('zhihu', 'hot', {'limit': 5}))     # same entry: rows fetched at MAX_ROWS
    assert len(runs) == 1 and runs[0][-1] == str(oc.MAX_ROWS) and 'cached_age_s' in second and 'cached_age_s' not in first
    oc.opencli_read('zhihu', 'hot', fresh=True)
    assert len(runs) == 2
    oc.opencli_read('zhihu', 'feed')
    oc.opencli_read('zhihu', 'feed')
    assert len(runs) == 4                                                   # account-specific: never cached

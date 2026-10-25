"""D7: intent routing — the pattern fallback and the handler table (no network, no apps)."""
import json

from core import desktop_intents, desktop_router as intent_router


def test_legacy_patterns_are_the_offline_fallback():
    assert intent_router.legacy_intent('今天有什么日程') == 'calendar'
    assert intent_router.legacy_intent('读一下第2封') == 'mail_pick'
    assert intent_router.legacy_intent('微信给文件传输助手发：测试') == 'wechat_send'
    assert intent_router.legacy_intent('知乎热榜') == 'website'
    assert intent_router.legacy_intent('给我讲个笑话') == 'other'


def test_classify_is_none_without_the_decision_model():
    assert intent_router.classify('今天有什么日程') is None          # conftest disables the hosted model


def test_eval_sets_are_labelled_with_known_intents():
    for name in ('dev', 'dev2', 'heldout2'):
        rows = [json.loads(l) for l in open(f'eval/intent_v1/{name}.jsonl', encoding='utf-8') if l.strip()]
        assert rows and all(r['intent'] in intent_router.INTENTS for r in rows)


def test_handler_table(monkeypatch):
    import core.calendar_brief as cal
    import core.mail_reader as mail
    monkeypatch.setattr(desktop_intents.sys, 'platform', 'darwin')
    monkeypatch.setattr(cal, 'reply_for', lambda day: f'日程:{day}')
    monkeypatch.setattr(mail, 'pick_reply', lambda n, mode, summarize: f'邮件:{n}:{mode}')
    route = {'intent': 'calendar', 'day': 'tomorrow'}
    assert desktop_intents.handle(route, '明儿个忙不忙', model=None) == ('日程:tomorrow', 'calendar_fastpath')
    route = {'intent': 'mail_pick', 'mail_mode': 'summary'}
    assert desktop_intents.handle(route, '邮件列表里第4封帮我概括一下', model=None) == ('邮件:4:summary', 'mail_fastpath')
    assert desktop_intents.handle({'intent': 'other'}, '你好', model=None) is None


def test_user_method_without_a_failure_goes_to_the_model(tmp_path):
    from core.activity_log import ActivityLog
    log = ActivityLog(tmp_path)
    assert desktop_intents.handle({'intent': 'user_method'}, '我是这样做的：重启', model=None, activity_log=log) is None

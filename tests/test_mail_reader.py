"""D3: mail fast-path parsing and rendering (no Mail access)."""
from core import mail_reader as mr


def test_questions_and_picks():
    assert mr.ASK.search('有什么新邮件') and mr.ASK.search('看看未读邮件') and mr.ASK.search('check my new email')
    assert not mr.ASK.search('打开邮件')                          # opening the app is D1's job
    assert mr.answer('总结第 2 封邮件') is None                   # a pick, not a list request
    assert mr.pick('总结第2封') == ('summary', 2) and mr.pick('读一下第 3 封') == ('read', 3) and mr.pick('你好') is None


def test_list_text_and_sender_names():
    rows = [{'id': 1, 'date': '2026-10-21T01:03:17', 'sender': '"Ann Li" <ann@x.com>', 'subject': '周会改期', 'account': 'iCloud'}]
    text = mr.list_text(rows, 81)
    assert text.startswith('未读邮件 81 封，最新 1 封：') and '10-21 01:03 Ann Li：周会改期' in text
    assert mr.list_text([], 0) == '没有未读邮件。'
    assert mr.sender_name('bob@x.com') == 'bob@x.com'


def test_pick_out_of_range_and_summary_uses_given_model(monkeypatch):
    monkeypatch.setattr(mr, '_last_listed', [{'id': 7, 'date': '', 'sender': 'a', 'subject': 's', 'account': ''}])
    assert '只有 1 封' in mr.answer_pick('读第 3 封', lambda p: '')
    monkeypatch.setattr(mr, 'read', lambda i: {'id': i, 'sender': 'A <a@x>', 'subject': '报价', 'date': '2026-10-20T10:00:00',
                                               'text': '请在周五前确认报价。', 'truncated': False})
    seen = []
    out = mr.answer_pick('总结第 1 封', lambda p: seen.append(p) or '对方请你周五前确认报价。')
    assert '对方请你周五前确认报价' in out and '请在周五前确认报价' in seen[0]

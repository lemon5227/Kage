"""D4a: WeChat question parsing and reply rendering (no screen access)."""
from core import wechat_reader as wr


def test_questions():
    assert wr.ASK.search('微信有什么未读消息') and wr.ASK.search('看看微信谁找我') and wr.ASK.search('有新的微信消息吗')
    assert not wr.ASK.search('打开微信') and not wr.ASK.search('给文件传输助手发消息说你好')


def test_reply_lists_only_unread(monkeypatch):
    monkeypatch.setattr(wr, 'read_chat_list', lambda: [
        {'name': '腾讯新闻', 'preview': '新闻摘要', 'time': '18:53', 'unread': True, 'unread_count': 26},
        {'name': '公众号', 'preview': 'switch 游戏联盟', 'time': '16:05', 'unread': True, 'unread_count': None},
        {'name': 'DOTA', 'preview': '语音通话已经结束', 'time': '16:49', 'unread': False, 'unread_count': None}])
    text = wr.answer('微信有什么未读消息')
    assert '2 个会话有未读' in text and '腾讯新闻（18:53，26 条）' in text and '公众号（16:05，有新消息）' in text
    assert 'DOTA' not in text


def test_time_labels():
    for t in ('18:53', '昨天', '星期五', '06/27', '2025/12/01', '10月3日'):
        assert wr.TIME.match(t), t
    assert not wr.TIME.match('DOTA')

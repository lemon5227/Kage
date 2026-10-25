from core import activity_log, wechat_sender as ws


def test_parse():
    assert ws.parse('微信给文件传输助手发：测试一下') == ('文件传输助手', '测试一下')
    assert ws.parse('用微信给Wenbo yan发消息：晚上吃啥') == ('Wenbo yan', '晚上吃啥')
    assert ws.parse('给张三发个微信：明天开会') == ('张三', '明天开会')
    assert ws.parse('在微信上给 wenbo yan 说 你好') == ('wenbo yan', '你好')
    assert ws.parse('微信有什么未读消息') is None
    assert ws.parse('打开微信') is None


def test_confirm_first_except_allowlist(monkeypatch):
    sent = []
    monkeypatch.setattr(ws, 'send', lambda to, text: sent.append((to, text)) or f'已发给 {to}：{text}')
    ws._pending.clear()
    assert ws.answer('微信给文件传输助手发：hi').startswith('已发给') and sent == [('文件传输助手', 'hi')]
    assert ws.answer('微信给Wenbo Yan发：hi2').startswith('已发给')            # case/space-insensitive allowlist
    reply = ws.answer('给张三发个微信：明天开会')
    assert '说“确认”发送' in reply and len(sent) == 2                          # nothing sent yet
    assert ws.answer('取消') == '好，不发了。' and len(sent) == 2
    assert ws.answer('确认') is None                                            # nothing pending any more
    ws.answer('给张三发个微信：明天开会')
    assert ws.answer('确认').startswith('已发给') and sent[-1] == ('张三', '明天开会')


def test_count_and_log_status():
    assert ws._count(['Kage D4b 测试2，来自小助手', '别的'], 'Kage D4b 测试 2，来自小助手') == 1
    assert activity_log.classify('wechat_send', '已发给 张三：x', [])[0] == 'ok'
    assert activity_log.classify('wechat_send', '要用微信发给“张三”：x', [])[0] == 'chat'
    assert activity_log.classify('wechat_send', '没有发送：微信搜索里没找到', [])[0] == 'failed'

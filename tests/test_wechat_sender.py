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
    monkeypatch.setattr(ws, 'lookup', lambda to: (True, []))
    ws._pending.clear()
    assert ws.answer('微信给文件传输助手发：hi').startswith('已发给') and sent == [('文件传输助手', 'hi')]
    assert ws.answer('微信给Wenbo Yan发：hi2').startswith('已发给')            # case/space-insensitive allowlist
    reply = ws.answer('给张三发个微信：明天开会')
    assert '说“确认”发送' in reply and len(sent) == 2                          # nothing sent yet
    assert ws.answer('取消') == '好，不发了。' and len(sent) == 2
    assert ws.answer('确认').startswith('现在没有等你确认')                      # nothing pending any more
    ws.answer('给张三发个微信：明天开会')
    assert ws.answer('确认').startswith('已发给') and sent[-1] == ('张三', '明天开会')


def test_count_and_log_status():
    assert ws._count(['Kage D4b 测试2，来自小助手', '别的'], 'Kage D4b 测试 2，来自小助手') == 1
    assert activity_log.classify('wechat_send', '已发给 张三：x', [])[0] == 'ok'
    assert activity_log.classify('wechat_send', '要用微信发给“张三”：x', [])[0] == 'chat'
    assert activity_log.classify('wechat_send', '没有发送：微信搜索里没找到', [])[0] == 'failed'
    assert activity_log.classify('wechat_send', '现在没有等你确认的微信消息，什么都没发。', [])[0] == 'chat'


def test_unknown_name_suggests_similar(monkeypatch):
    sent = []
    monkeypatch.setattr(ws, 'send', lambda to, text: sent.append((to, text)) or f'已发给 {to}：{text}')
    monkeypatch.setattr(ws, 'lookup', lambda to: (False, ['Wenbo yan', 'wenbo2']) if 'wenbo' in to else (False, []))
    ws._pending.clear()
    reply = ws.answer('微信给wenbo yen发：hi')
    assert '没有叫“wenbo yen”的人' in reply and '“Wenbo yan”' in reply and not sent     # never sent unasked
    assert ws.answer('发给 wenbo2').startswith('好，改成发给“wenbo2”')
    assert ws.answer('确认') == '已发给 wenbo2：hi'
    assert '名字是不是说错了' in ws.answer('微信给查无此人发：hi') and len(sent) == 1


def test_bare_confirm_after_wechat_turn_is_not_left_to_the_model(monkeypatch):
    monkeypatch.setattr(ws, 'lookup', lambda to: (False, []))
    ws._pending.clear()
    assert '名字是不是说错了' in ws.answer('微信给查无此人发：hi')
    assert ws.answer('确认') == '现在没有等你确认的微信消息，什么都没发。'
    ws._last_reply['time'] = 0
    assert ws.answer('确认') is None                      # long after: not ours


def test_unverified_send_claim_is_flagged():
    assert activity_log.classify('agentic_loop', '已发给 Wenbo yan：x', [])[0] == 'unverified'


def test_title_ignores_icons(monkeypatch, tmp_path):
    from pathlib import Path
    image = tmp_path / 'x.png'
    image.write_bytes(b'')
    boxes = [{'text': 'Wenbo yan', 'x': 700, 'y': 40, 'w': 150, 'h': 30}, {'text': '●••', 'x': 1900, 'y': 44, 'w': 30, 'h': 17},
             {'text': 'く', 'x': 640, 'y': 40, 'w': 20, 'h': 30}, {'text': '你好', 'x': 900, 'y': 600, 'w': 60, 'h': 30}]
    monkeypatch.setattr(ws, '_main_window', lambda: 1)
    monkeypatch.setattr(ws.wechat_reader, 'capture', lambda wid: image)
    monkeypatch.setattr(ws.wechat_reader, 'ocr', lambda img: (boxes, 2000, 1400))
    assert ws._read_pane() == ('Wenbo yan', ['你好'])

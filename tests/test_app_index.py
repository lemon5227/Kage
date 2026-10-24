"""D1: what the user calls an app -> the installed application (index built from fixed rows, no Spotlight)."""
from core.tools import app_index as ai


def row(name, display, bundle):
    names = {ai.normalize(n) for n in (name, display, *ai.ALIASES.get(bundle, []))}
    return {'path': f'/Applications/{name}.app', 'name': name, 'display': display, 'bundle_id': bundle,
            'names': sorted(names)}


INDEX = [row('WeChat', '微信', 'com.tencent.xinWeChat'), row('Lark', '飞书', 'com.electron.lark'),
         row('Photos', '照片', 'com.apple.Photos'), row('Visual Studio Code', 'Visual Studio Code', 'com.microsoft.VSCode'),
         row('Google Chrome', 'Google Chrome', 'com.google.Chrome'), row('Notes', '备忘录', 'com.apple.Notes'),
         row('Numbers', 'Numbers', 'com.apple.iWork.Numbers'), row('Notion', 'Notion', 'notion.id')]


def test_names_aliases_suffixes_and_typos_resolve():
    for query, name in [('微信', 'WeChat'), ('微信app', 'WeChat'), ('WeChat 客户端', 'WeChat'), ('飞书', 'Lark'),
                        ('vscode', 'Visual Studio Code'), ('谷歌浏览器', 'Google Chrome'), ('备忘录', 'Notes'),
                        ('wechta', 'WeChat')]:
        status, apps = ai.resolve(query, INDEX)
        assert status == 'ok' and apps[0]['name'] == name, query


def test_unknown_or_ambiguous_names_never_open_a_guess():
    assert ai.resolve('photoshop', INDEX)[0] == 'missing'          # not "photos"
    status, apps = ai.resolve('no', INDEX)                        # Notes, Numbers, Notion
    assert status == 'ambiguous' and len(apps) >= 2
    assert ai.resolve('', INDEX) == ('missing', [])


def test_open_requests_are_parsed_and_web_or_file_requests_are_not():
    for text, app in [('打开微信', '微信'), ('帮我打开飞书', '飞书'), ('启动一下 VS Code', 'VS Code'), ('把日历打开', '日历'),
                      ('帮我把备忘录打开一下', '备忘录'), ('open Safari', 'Safari'), ('launch Cursor', 'Cursor'),
                      ('开一下谷歌浏览器', '谷歌浏览器'), ('打开 UU 远程吧', 'UU 远程')]:
        assert ai.parse_open_request(text) == app, text
    for text in ('打开 github.com', '打开 meeting-notes.txt', '帮我打开这个网页', '今天天气怎么样',
                 '打开微信然后给张三发消息说我晚点到，记得要礼貌一点并且提到明天的会议'):
        assert ai.parse_open_request(text) is None, text

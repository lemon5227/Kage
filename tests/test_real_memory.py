"""A3b: earlier real successes are offered only to sufficiently similar new requests."""
from core.evolution.real_memory import RealExperience, render, usable
from core.trajectories import TrajectoryRecorder

WRITE = {'name': 'write_file', 'arguments': {'path': '/tmp/w/hello.txt', 'content': 'hi'}, 'success': True}


def add(rec, turn_id, text, *, source='real', feedback=None, ok=True):
    rec.begin(turn_id, text, source=source)
    rec.step([{'role': 'user', 'content': text}], [], type('R', (), {
        'text': '', 'tool_calls': [{'name': 'write_file', 'arguments': WRITE['arguments']}]})())
    rec.finish('写好了。', [{**WRITE, 'success': ok}])
    if feedback:
        rec.feedback(turn_id, feedback)


def test_only_confirmed_or_checked_teacher_turns_are_usable(tmp_path):
    rec = TrajectoryRecorder(tmp_path)
    add(rec, 'a', '在 work 目录建 hello.txt 写你好')                       # auto-checked student: not enough
    add(rec, 'b', '在 work 目录建 hello.txt 写你好', feedback='up')
    add(rec, 'c', '在 work 目录建 hello.txt 写你好', source='teacher')        # teacher + auto check
    add(rec, 'd', '在 work 目录建 hello.txt 写你好', feedback='down')
    assert [usable(rec.get(i)) for i in 'abcd'] == [False, True, True, False]


def test_gate_admits_similar_requests_and_rejects_unrelated(tmp_path):
    rec = TrajectoryRecorder(tmp_path)
    add(rec, 'b', '在桌面的 notes 文件夹里新建 todo.txt，写上明天要做的三件事', feedback='up')
    add(rec, 'x', '帮我查一下明天上海的天气，然后提醒我带伞', feedback='up')
    mem = RealExperience(tmp_path)
    hit, score = mem.retrieve('在桌面的 notes 文件夹里新建 shopping.txt，写上要买的东西')
    assert hit is not None and hit['id'] == 'b' and score >= 0.45
    miss, low = mem.retrieve('把这首歌的音量调小一点')
    assert miss is None and low < 0.45
    hint = render(hit)
    assert 'write_file' in hint and '不要照抄' in hint and len(hint) <= 1500


def test_empty_store_gives_nothing(tmp_path):
    assert RealExperience(tmp_path / 'none').retrieve('任何请求') == (None, 0.0)


def test_chinese_only_requests_are_compared(tmp_path):
    rec = TrajectoryRecorder(tmp_path)
    add(rec, 'b', '把下载文件夹里的截图按日期整理到图片文件夹', feedback='up')
    add(rec, 'x', '帮我查一下明天上海的天气，然后提醒我带伞', feedback='up')
    mem = RealExperience(tmp_path)
    hit, _ = mem.retrieve('把下载文件夹里的截图按日期整理一下')
    assert hit is not None and hit['id'] == 'b'
    assert mem.retrieve('今天晚上吃什么好')[0] is None

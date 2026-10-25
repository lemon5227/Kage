"""Usage log: statuses, failure follow-up with the user's own method, summary."""
from core.activity_log import ActivityLog, classify, wants_log


def test_statuses():
    assert classify('open_app_fastpath', '已打开微信。', [])[0] == 'ok'
    assert classify('open_app_fastpath', '没有找到叫“Photoshop”的应用', [])[0] == 'failed'
    assert classify('agentic_loop', '已添加。', [])[0] == 'unverified'          # claimed, no tool ran
    assert classify('agentic_loop', '好的', [{'name': 'doc_replace', 'success': False, 'error_type': 'NotUnique'}])[0] == 'failed'
    assert classify('agentic_loop', '已修改。', [{'name': 'doc_replace', 'success': True}])[0] == 'ok'
    assert classify('agentic_loop', '你好呀', [])[0] == 'chat'


def test_failure_then_user_method_is_attached_and_rendered(tmp_path):
    log = ActivityLog(tmp_path)
    log.record(request='把 todo.txt 里的 X 改成 Y', reply='没改成', path='agentic_loop',
               tools=[{'name': 'doc_replace', 'success': False, 'error_type': 'NotUnique', 'error_message': '出现 2 次'}])
    assert log.attach_user_method('今天天气不错') is None                       # not an explanation
    target = log.attach_user_method('我是这样做的：在 TextEdit 里用查找替换，只换第一处')
    assert target is not None and target['tools'][0]['name'] == 'doc_replace'
    assert log.attach_user_method('我自己又做了一遍') is None                  # already explained
    md = next(tmp_path.glob('*.md')).read_text()
    assert '❌' in md and '你的做法' in md and '查找替换' in md
    assert (tmp_path / 'methods.jsonl').exists()
    assert '失败 1' in log.summary()


def test_show_log_requests():
    assert wants_log('看看今天的使用日志') and wants_log('今天我都干了啥') and not wants_log('打开日历')

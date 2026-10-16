"""A2: usage-time trajectory store — recording, feedback labels, hold-out, redacted export."""
import json

from core.model_provider import ModelResponse
from core.trajectories import (RecordingProvider, TrajectoryRecorder, evidence, export_redacted, redact_text,
                               split_of)


class Model:
    def __init__(self, replies):
        self.replies = list(replies)
        self.model_name = 'fake'

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        return self.replies.pop(0)


WRITE = {'name': 'write_file', 'arguments': {'path': '/Users/alice/notes/todo.md', 'content': 'x'}, 'success': True}


def turn(rec, model, turn_id, calls):
    rec.begin(turn_id, 'Save my todo list for alice@example.com')
    msgs = [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'Save my todo list, call +1 415 555 0100'}]
    model.generate(messages=msgs, tools=[{'type': 'function', 'function': {'name': 'write_file'}}])
    model.generate(messages=msgs + [{'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': 'write_file', 'arguments': json.dumps(WRITE['arguments'])}}]}], tools=[])
    return rec.finish('Saved.', calls)


def test_records_steps_in_student_format_and_labels(tmp_path):
    rec = TrajectoryRecorder(tmp_path / 't')
    model = RecordingProvider(Model([ModelResponse(text='', tool_calls=[{'name': 'write_file', 'arguments': WRITE['arguments']}]),
                                     ModelResponse(text='Saved.')]), rec)
    record = turn(rec, model, 'ws-1', [WRITE])
    assert record['kind'] == 'task' and len(record['steps']) == 2
    assert record['auto_check'] == {'all_tools_ok': True, 'wrote_files': ['/Users/alice/notes/todo.md']}
    assert evidence(record) == 'auto'
    assert rec.feedback('ws-1', 'down')['feedback'] == 'down' and evidence(rec.get('ws-1')) == 'failed'
    assert evidence(rec.feedback('ws-1', 'up')) == 'user'
    assert [r['id'] for r in rec.list()] == ['ws-1']


def test_nothing_recorded_outside_a_turn_or_when_disabled(tmp_path):
    rec = TrajectoryRecorder(tmp_path / 't', enabled=False)
    model = RecordingProvider(Model([ModelResponse(text='hi')] * 3), rec)
    model.generate(messages=[{'role': 'user', 'content': 'x'}])
    rec.begin('ws-2', 'hello')
    model.generate(messages=[{'role': 'user', 'content': 'hello'}])
    assert rec.finish('hi', []) is None and rec.list() == []


def test_chat_turn_without_tools_has_no_evidence(tmp_path):
    rec = TrajectoryRecorder(tmp_path / 't')
    model = RecordingProvider(Model([ModelResponse(text='hi')]), rec)
    rec.begin('ws-3', 'hello')
    model.generate(messages=[{'role': 'user', 'content': 'hello'}])
    record = rec.finish('hi', [])
    assert record['kind'] == 'chat' and evidence(record) == 'none'


def test_holdout_is_deterministic_and_about_one_in_ten():
    ids = [f'ws-{i}' for i in range(2000)]
    held = sum(split_of(i) == 'eval' for i in ids)
    assert 120 < held < 280 and split_of('ws-7') == split_of('ws-7')


def test_redaction_masks_personal_data():
    text = ('mail alice@example.com, call +1 (415) 555-0100, key sk-abcdefghijklmnopqrstuv, '
            'token=abc123 at /Users/alice/Documents/x.txt from 192.168.1.20; Alice wrote it')
    out = redact_text(text, ('alice',))
    for leaked in ('alice@example.com', '555-0100', 'sk-abc', 'abc123', '/Users/alice', '192.168', 'Alice'):
        assert leaked not in out, leaked
    assert '/Users/USER/Documents/x.txt' in out


def test_export_only_successful_train_turns_redacted(tmp_path):
    rec = TrajectoryRecorder(tmp_path / 't')
    ids = []
    for i in range(40):
        model = RecordingProvider(Model([ModelResponse(text='', tool_calls=[{'name': 'write_file', 'arguments': WRITE['arguments']}]),
                                         ModelResponse(text='Saved.')]), rec)
        turn(rec, model, f'ws-{i}', [WRITE] if i % 4 else [{**WRITE, 'success': False}])
        ids.append(f'ws-{i}')
    stats = export_redacted(rec, tmp_path / 'out.jsonl', extra_names=('alice',))
    rows = [json.loads(l) for l in (tmp_path / 'out.jsonl').read_text().splitlines()]
    expected = [i for n, i in enumerate(ids) if n % 4 and split_of(i) == 'train']
    assert stats['exported_turns'] == len(expected) and len(rows) == 2 * len(expected)
    blob = json.dumps(rows)
    assert 'alice' not in blob.lower() and '555 0100' not in blob
    assert all(split_of(r['task_id']) == 'train' for r in rows)
    call = rows[1]['messages'][-1]['tool_calls'][0]['function']
    assert isinstance(call['arguments'], dict) and call['arguments']['path'] == '/Users/USER/notes/todo.md'


def test_teacher_redo_shares_the_split_of_its_task(tmp_path):
    rec = TrajectoryRecorder(tmp_path / 't')
    for i in range(40):
        rec.begin(f'ws-{i}-teacher', 'task', source='teacher', parent=f'ws-{i}')
        r = rec.finish('ok', [WRITE])
        assert r['split'] == split_of(f'ws-{i}') and r['parent'] == f'ws-{i}' and r['source'] == 'teacher'

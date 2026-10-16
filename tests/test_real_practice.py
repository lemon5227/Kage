"""A4: idle practice on teacher-made variants of real file tasks."""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evolution.real_practice import (PracticeError, PracticeScheduler, make_task, practice_round, report_notice,
                                          run_check, seeds, validate_check)
from core.trajectories import TrajectoryRecorder, evidence

CHECK = ("import pathlib\n"
         "def check(ws):\n"
         "    p = pathlib.Path(ws) / 'total.txt'\n"
         "    return p.exists() and p.read_text().strip() == '6'\n")
TASK = {'instruction': '读取 {WS}/nums.txt 里的数字，求和后写到 {WS}/total.txt', 'files': {'nums.txt': '1\n2\n3\n'},
        'check': CHECK}


class Teacher:
    def __init__(self, reply=None):
        self.reply, self.calls = reply or json.dumps(TASK, ensure_ascii=False), 0

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.0):
        self.calls += 1
        return SimpleNamespace(text=self.reply)


def real_turn(store, turn_id, *, feedback=None, created='2026-10-16T10:00:00'):
    store.begin(turn_id, '把 notes 里的数字加起来写到 total.txt')
    store.finish('好了', [{'name': 'fs_write', 'arguments': {'path': '/tmp/x/total.txt'}, 'success': True}])
    r = store.get(turn_id)
    r['created'] = created
    store._write(r)
    if feedback:
        store.feedback(turn_id, feedback)


def test_check_code_is_read_only():
    validate_check(CHECK)
    for bad in ("import subprocess\ndef check(ws):\n    return True\n",
                "import os\ndef check(ws):\n    os.remove(ws)\n    return True\n",
                "def check(ws):\n    open(ws + '/x', 'w').write('1')\n    return True\n",
                "def nope(ws):\n    return True\n"):
        with pytest.raises(PracticeError):
            validate_check(bad)


def test_teacher_variant_is_parsed_and_checked(tmp_path):
    task = make_task(Teacher(), {'user_input': '求和'})
    assert '{WS}' in task['instruction'] and task['files'] == {'nums.txt': '1\n2\n3\n'}
    with pytest.raises(PracticeError):
        make_task(Teacher('not json'), {'user_input': 'x'})
    with pytest.raises(PracticeError):
        make_task(Teacher(json.dumps({**TASK, 'files': {'../evil': 'x'}})), {'user_input': 'x'})
    (tmp_path / 'total.txt').write_text('6\n')
    assert run_check(CHECK, tmp_path) is True
    (tmp_path / 'total.txt').write_text('7')
    assert run_check(CHECK, tmp_path) is False
    assert run_check("def check(ws):\n    raise ValueError()\n", tmp_path) is False


def test_seeds_prefer_failed_real_file_tasks(tmp_path):
    store = TrajectoryRecorder(tmp_path / 't')
    real_turn(store, 'ok-new', created='2026-10-16T12:00:00')
    real_turn(store, 'bad', feedback='down', created='2026-10-16T09:00:00')
    real_turn(store, 'ok-old', created='2026-10-15T12:00:00')
    assert [s['id'] for s in seeds(store, 3)] == ['bad', 'ok-new', 'ok-old']


class Runner:
    """Stands in for the app's agent loop: does the arithmetic in the named directory."""
    def __init__(self, recorder, solve=True):
        self.recorder, self.solve = recorder, solve

    async def run(self, user_input, current_emotion='neutral'):
        ws = re.search(r'(/\S+)/nums\.txt', user_input).group(1)
        self.recorder.step([{'role': 'user', 'content': user_input}], [],
                           SimpleNamespace(text='', tool_calls=[{'name': 'fs_write', 'arguments': {'path': ws}}]))
        if self.solve:
            total = sum(int(x) for x in Path(ws, 'nums.txt').read_text().split())
            Path(ws, 'total.txt').write_text(str(total))
        return SimpleNamespace(final_text='done', tool_calls_executed=[
            {'name': 'fs_write', 'arguments': {'path': f'{ws}/total.txt'}, 'success': True}])


def test_round_records_practice_trajectories_and_reports(tmp_path):
    store = TrajectoryRecorder(tmp_path / 't')
    real_turn(store, 'seed-1', feedback='down')
    teacher = Teacher()
    summary = asyncio.run(practice_round(store=store, teacher=teacher, make_runner=lambda rec: Runner(rec),
                                         variants=2, k_seeds=2, workdir=tmp_path / 'ws'))
    assert summary['tasks'] == 2 and summary['passed'] == 2 and teacher.calls == 2
    records = [store.get(i['id']) for i in summary['items']]
    assert all(r['source'] == 'practice' and r['parent'] == 'seed-1' and evidence(r) == 'auto' for r in records)
    assert all(r['split'] == store.get('seed-1')['split'] for r in records)
    note = report_notice(summary)
    assert note['kind'] == 'learning_report' and '2 道' in note['body']
    failing = asyncio.run(practice_round(store=store, teacher=Teacher(), make_runner=lambda rec: Runner(rec, solve=False),
                                         variants=1, k_seeds=1, workdir=tmp_path / 'ws2'))
    assert failing['passed'] == 0 and evidence(store.get(failing['items'][0]['id'])) == 'failed'


def test_scheduler_runs_only_when_everything_allows(tmp_path):
    started = []

    async def start_round(**kw):
        started.append(kw)
        return {'tasks': 1, 'passed': 1, 'items': [], 'errors': []}

    class Notices:
        def __init__(self):
            self.rows = []

        def add(self, n):
            self.rows.append(n)
    state = {'last': None, 'model': True}
    notices = Notices()
    sched = PracticeScheduler({'practice': True, 'practice_rounds_per_day': 1}, last_user_time=lambda: state['last'],
                              model_ready=lambda: state['model'], start_round=start_round, notices=notices,
                              state_path=tmp_path / 'state.json')
    assert sched.should_run(1e9) == (True, 'ok')
    state['last'] = 1e9 - 60
    assert sched.should_run(1e9)[1] == 'user active'
    state['last'], state['model'] = None, False
    assert sched.should_run(1e9)[1] == 'local model not running'
    state['model'] = True

    async def go():
        import datetime
        await sched.collect(datetime.datetime.now())
        await sched.task
    asyncio.run(go())
    assert len(started) == 1 and len(notices.rows) == 1
    assert sched.should_run(1e9)[1] == 'daily rounds used'
    off = PracticeScheduler({}, last_user_time=lambda: None, model_ready=lambda: True, start_round=start_round,
                            notices=notices, state_path=tmp_path / 's2.json')
    assert off.should_run(1e9) == (False, 'practice is off')

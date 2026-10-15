"""Vertical slice of the learning stream with fake student/teacher/proposer."""
import json
from pathlib import Path

import pytest

from core.evolution.contracts import Candidate, RunResult
from core.evolution.stream import StreamLearner, TeacherCache
from core.evolution.stream_tasks import make_task

EMPTY = Candidate('no-skills', (), 'skill', '/tmp/none', 'e' * 64)


def result(tmp, run_id, score, rows, chain=None):
    path = Path(tmp) / f'{run_id}.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return RunResult(run_id, 'passed' if score >= 1 else 'failed', score, str(path),
                     metadata={'chain': chain or [{'stop_reason': 'model_returned'}]})


class World:
    """Student can only solve a family once the library holds that family's skill."""
    def __init__(self, tmp):
        self.tmp, self.teacher_calls, self.proposals = tmp, 0, 0

    def student(self, cand, task, run_id):
        has = task['family'] in cand.hypothesis
        if task.get('negative'):
            return result(self.tmp, run_id, 1.0, [{'action': {'name': 'read_file', 'arguments': {}}, 'observation': {'success': True}}])
        if has:
            return result(self.tmp, run_id, 1.0, [{'action': {'name': 'skill_call', 'arguments': {'skill_id': task['family']}},
                                                   'observation': {'success': True}}])
        return result(self.tmp, run_id, 0.0, [{'action': {'name': 'read_file', 'arguments': {}}, 'observation': {'success': True}}])

    def solve(self, task):
        self.teacher_calls += 1
        return result(self.tmp, 'teacher-' + task['task_id'], 1.0,
                      [{'action': {'name': 'write_file', 'arguments': {}}, 'observation': {'success': True}}])

    def propose(self, parent, task, demo):
        self.proposals += 1
        return Candidate(f'skill-{self.proposals}', (parent.candidate_id,), 'skill', '/tmp/x',
                         f'{self.proposals:064d}', parent.hypothesis + ' ' + task['family'])


def stream_tasks(n=6):
    return [make_task('log_aggregation', 1000 + i) for i in range(n)]


def test_skill_arm_learns_once_then_reuses(tmp_path):
    world = World(tmp_path)
    learner = StreamLearner(tmp_path / 'A4', 'A4', bootstrap=EMPTY, run_student=world.student,
                            teacher=TeacherCache(tmp_path / 'cache', world.solve), propose_skill=world.propose)
    rows = [learner.step(t) for t in stream_tasks()]
    assert rows[0]['solved_by_student'] is False and rows[0]['learning']['accepted'] is True
    assert all(r['solved_by_student'] for r in rows[1:])
    assert world.teacher_calls == 1 and world.proposals == 1
    assert learner.competence.skills['log_aggregation'].status == 'active'
    ev = learner.evaluate([make_task('log_aggregation', 9000), make_task('read_preserve', 9001)], 'cp1')
    assert ev['passed'] == 2 and ev['misuse'] == 0


def test_raw_arm_never_asks_or_learns(tmp_path):
    world = World(tmp_path)
    learner = StreamLearner(tmp_path / 'A0', 'A0', bootstrap=EMPTY, run_student=world.student,
                            teacher=None, propose_skill=None)
    rows = [learner.step(t) for t in stream_tasks(3)]
    assert not any(r['solved_by_student'] or r['helped'] for r in rows) and world.teacher_calls == 0


def test_proactive_arm_asks_before_attempt_when_competence_low(tmp_path):
    world = World(tmp_path)
    def bad_propose(parent, task, demo):          # learning keeps failing -> competence stays low
        raise ValueError('invalid candidate')
    learner = StreamLearner(tmp_path / 'A5', 'A5', bootstrap=EMPTY, run_student=world.student,
                            teacher=TeacherCache(tmp_path / 'cache5', world.solve), propose_skill=bad_propose)
    rows = [learner.step(t) for t in stream_tasks(4)]
    assert 'student_score' in rows[0] and 'student_score' in rows[1]     # explores first
    assert 'student_score' not in rows[2] and rows[2]['helped']            # then asks first
    assert learner.competence.help_log[-1]['when'] == 'before_attempt'


def test_teacher_cache_shared_and_replay_guard(tmp_path):
    world = World(tmp_path)
    cache = TeacherCache(tmp_path / 'shared', world.solve)
    for arm in ('A4', 'A5'):
        learner = StreamLearner(tmp_path / arm, arm, bootstrap=EMPTY, run_student=world.student,
                                teacher=cache, propose_skill=world.propose)
        learner.step(stream_tasks(1)[0])
    assert world.teacher_calls == 1                                         # cached across arms
    again = StreamLearner(tmp_path / 'A4', 'A4', bootstrap=EMPTY, run_student=world.student,
                          teacher=cache, propose_skill=world.propose)
    assert again.library.candidate_id == 'skill-1'                          # library persisted
    with pytest.raises(ValueError):
        again.step(stream_tasks(1)[0])
    with pytest.raises(ValueError):
        again.step(make_task('log_aggregation', 9005))                      # eval split cannot learn


def test_read_only_demo_is_not_turned_into_a_skill(tmp_path):
    world = World(tmp_path)
    def student_breaks_negative(cand, task, run_id):
        return result(tmp_path, run_id, 0.0, [{'action': {'name': 'skill_call', 'arguments': {'skill_id': 'x'}},
                                              'observation': {'success': True}}])
    def teacher_reads(task):
        return result(tmp_path, 't-' + task['task_id'], 1.0, [{'action': {'name': 'read_file', 'arguments': {}}, 'observation': {'success': True}}])
    learner = StreamLearner(tmp_path / 'n', 'A4', bootstrap=EMPTY, run_student=student_breaks_negative,
                            teacher=TeacherCache(tmp_path / 'cn', teacher_reads), propose_skill=world.propose)
    row = learner.step(make_task('read_preserve', 1010))
    assert 'learning' not in row and world.proposals == 0
    assert learner.competence.skills['x'].successes == 0                    # misuse counted against the skill


def test_interrupted_checkpoint_resumes_per_task(tmp_path):
    import json as _json
    from core.evolution.contracts import Candidate, RunResult
    from core.evolution.stream import StreamLearner
    from core.evolution.stream_tasks import make_task
    ran = []

    def run(candidate, task, run_id):
        ran.append(task['task_id'])
        return RunResult(run_id, 'passed', 1.0, '', {}, '')
    boot = Candidate('b', (), 'skill', str(tmp_path), 'd' * 64)
    tasks = [make_task('log_aggregation', 9000 + i) for i in range(3)]
    learner = StreamLearner(tmp_path / 'A0', 'A0', bootstrap=boot, run_student=run, teacher=None, propose_skill=None)
    (tmp_path / 'A0' / 'checkpoints.jsonl').write_text(_json.dumps(
        {'checkpoint': 'cp0', 'task_id': tasks[0]['task_id'], 'score': 0.0, 'misuse': False}) + '\n')
    summary = learner.evaluate(tasks, 'cp0')
    assert ran == [t['task_id'] for t in tasks[1:]]          # only the unfinished tasks run
    assert (summary['passed'], summary['total']) == (2, 3)    # summary covers the whole checkpoint
    assert learner.evaluate(tasks, 'cp0')['total'] == 3 and len(ran) == 2


def test_teacher_cache_pays_once_under_parallel_arms(tmp_path):
    import threading
    from core.evolution.contracts import RunResult
    from core.evolution.stream import TeacherCache
    calls = []

    def solve(task):
        calls.append(task['task_id'])
        import time
        time.sleep(0.05)
        return RunResult('r', 'passed', 1.0, '', {}, '')
    caches = [TeacherCache(tmp_path / 'cache', solve) for _ in range(4)]
    threads = [threading.Thread(target=c.get, args=({'task_id': 't1'},)) for c in caches]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert calls == ['t1']


def test_crashed_runs_raise_and_are_not_recorded(tmp_path):
    import pytest as _pytest
    from core.evolution.contracts import Candidate, RunResult
    from core.evolution.stream import InfrastructureError, StreamLearner, TeacherCache
    from core.evolution.stream_tasks import make_task
    boot = Candidate('b', (), 'skill', str(tmp_path), 'd' * 64)

    def crashed(candidate, task, run_id):
        return RunResult(run_id, 'crashed', 0.0, '', {}, '')
    learner = StreamLearner(tmp_path / 'A0', 'A0', bootstrap=boot, run_student=crashed, teacher=None, propose_skill=None)
    with _pytest.raises(InfrastructureError):
        learner.step(make_task('log_aggregation', 1000))
    with _pytest.raises(InfrastructureError):
        learner.evaluate([make_task('log_aggregation', 9000)], 'cp0')
    assert not (tmp_path / 'A0' / 'stream.jsonl').exists() and not (tmp_path / 'A0' / 'checkpoints.jsonl').exists()
    assert learner.done == set()

    calls = []

    def teacher_solve(task):
        calls.append(1)
        return RunResult('t', 'crashed', 0.0, '', {}, '')
    cache = TeacherCache(tmp_path / 'cache', teacher_solve)
    with _pytest.raises(InfrastructureError):
        cache.get({'task_id': 'x'})
    assert not (tmp_path / 'cache' / 'x.json').exists()


def test_budget_exhausted_teacher_stops_learning_and_is_not_cached(tmp_path):
    import pytest as _pytest
    from core.evolution.contracts import Candidate, RunResult
    from core.evolution.stream import StreamLearner, TeacherBudgetExhausted, TeacherCache
    from core.evolution.stream_tasks import make_task
    boot = Candidate('b', (), 'skill', str(tmp_path), 'd' * 64)

    def student(candidate, task, run_id):
        return RunResult(run_id, 'failed', 0.0, '', {}, '')
    cache = TeacherCache(tmp_path / 'cache', lambda task: RunResult('t', 'budget_exhausted', 0.0, '', {}, ''))
    learner = StreamLearner(tmp_path / 'A4', 'A4', bootstrap=boot, run_student=student, teacher=cache,
                            propose_skill=lambda *a: None)
    with _pytest.raises(TeacherBudgetExhausted):
        learner.step(make_task('log_aggregation', 1000))
    assert not list((tmp_path / 'cache').glob('*.json'))
    assert not (tmp_path / 'A4' / 'stream.jsonl').exists() and learner.done == set()

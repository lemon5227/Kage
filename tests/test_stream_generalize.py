"""A4g/A4m: a new skill must also work on earlier same-family stream tasks; one generalization retry."""
import json

from core.evolution.contracts import Candidate, RunResult
from core.evolution.stream import ARMS, MemoryStore, StreamLearner
from core.evolution.stream_tasks import make_task


def trace(tmp_path, name, rows):
    p = tmp_path / f'{name}.jsonl'
    p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return str(p)


class World:
    """Student passes with the 'general' skill everywhere, with 'narrow' only on its source task."""
    def __init__(self, tmp_path):
        self.tmp, self.hints, self.runs = tmp_path, [], []

    def run_student(self, candidate, task, run_id):
        self.runs.append((candidate.candidate_id, task['task_id'], run_id))
        if candidate.candidate_id == 'boot':
            return RunResult(run_id, 'failed', 0.0, trace(self.tmp, run_id, []), {}, '')
        ok = candidate.candidate_id == 'general' or task['task_id'].endswith('1004')
        rows = [{'action': {'name': 'skill_call', 'arguments': {'skill_id': 's'}}, 'observation': {'success': True}}]
        return RunResult(run_id, 'passed' if ok else 'failed', 1.0 if ok else 0.0, trace(self.tmp, run_id, rows), {}, '')

    def propose(self, parent, task, demo, hint=None):
        self.hints.append(hint)
        name = 'general' if hint else 'narrow'
        return Candidate(name, (parent.candidate_id,), 'skill', str(self.tmp), name * 8)


class Teacher:
    def __init__(self, tmp_path):
        self.tmp = tmp_path

    def get(self, task):
        rows = [{'action': {'name': 'write_file', 'arguments': {'path': 'x.py', 'content': 'x'}},
                 'observation': {'success': True, 'content': 'ok'}}]
        return RunResult('t', 'passed', 1.0, trace(self.tmp, 'teacher-' + task['task_id'], rows), {}, '')


def stream(tmp_path, arm, world, memory=None):
    boot = Candidate('boot', (), 'skill', str(tmp_path), 'b' * 64)
    learner = StreamLearner(tmp_path / arm, arm, bootstrap=boot, run_student=world.run_student,
                            teacher=Teacher(tmp_path), propose_skill=world.propose, memory=memory)
    return learner, [learner.step(make_task('log_aggregation', 1000 + i)) for i in (0, 2, 4)]


def test_narrow_skill_is_rejected_then_generalized(tmp_path):
    assert ARMS['A4g']['verify_family'] == 2 and ARMS['A4g']['generalize'] == 1
    world = World(tmp_path)
    learner, rows = stream(tmp_path, 'A4g', world)
    learning = rows[-1]['learning']
    assert learning['verify_tasks'] == ['stream-v1-log_aggregation-1002', 'stream-v1-log_aggregation-1000']
    assert learning['accepted'] is True and learning['child'] == 'general' and learning['generalized'] is True
    assert world.hints[-1] and 'stream-v1-log_aggregation-1000' not in world.hints[-1]     # instructions, not ids
    assert 'Implement' in world.hints[-1] or 'log' in world.hints[-1].lower()
    assert learner.library.candidate_id == 'general'


def test_plain_a4_keeps_source_only_acceptance(tmp_path):
    world = World(tmp_path)
    learner, rows = stream(tmp_path, 'A4', world)
    assert rows[-1]['learning']['accepted'] is True and learner.library.candidate_id == 'narrow'


def test_a4m_also_stores_the_demonstration(tmp_path):
    world = World(tmp_path)
    memory = MemoryStore(tmp_path / 'A4m' / 'memory.jsonl')
    learner, rows = stream(tmp_path, 'A4m', world, memory=memory)
    assert ARMS['A4m']['learn'] == 'both'
    assert len(memory.entries()) == 3 and rows[-1]['learning']['memory_stored'] is True
    assert learner.library.candidate_id == 'general'

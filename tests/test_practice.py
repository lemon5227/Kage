import json

import pytest

from core.evolution.competence import CompetenceModel
from core.evolution.contracts import Candidate, RunResult
from core.evolution.practice import PracticeRound
from core.evolution.stream_tasks import split_of

LIB = Candidate('lib', (), 'skill', '/nonexistent', 'f' * 64)


def competence():
    c = CompetenceModel()
    for ok in (True, False, True, False):
        c.record_task('log_aggregation', ok)
    c.record_task('interval_merge', False)
    for _ in range(5):
        c.record_task('read_preserve', True)
    return c


def student(tmp_path, solve_every=2):
    seen = []

    def run(candidate, task, run_id):
        assert candidate is LIB
        seen.append(task)
        trace = tmp_path / f'{run_id}.jsonl'
        trace.write_text(json.dumps({'action': {'name': 'skill_call', 'arguments': {'skill_id': 'count_log'}},
                                     'observation': {'success': True}}) + '\n')
        score = 1.0 if len(seen) % solve_every == 0 else 0.0
        return RunResult(run_id, 'passed' if score else 'failed', score, str(trace), {}, str(tmp_path))
    return run, seen


def test_practice_uses_only_practice_seeds_and_no_teacher(tmp_path):
    run, seen = student(tmp_path)
    comp = competence()
    pr = PracticeRound(tmp_path / 'p', comp, run_student=run)
    summary = pr.run(LIB, 6, label='r1')
    assert summary['tasks'] == 6 and len(seen) == 6
    assert all(split_of(int(t['task_id'].rsplit('-', 1)[1])) == 'practice' for t in seen)
    assert {t['family'] for t in seen} == {'log_aggregation', 'interval_merge'}   # negatives never drilled
    pr.run(LIB, 6, label='r2')
    ids = [t['task_id'] for t in seen]
    assert len(ids) == len(set(ids)) == 12                                        # no repeats across rounds


def test_failures_queue_and_round_summary(tmp_path):
    run, _ = student(tmp_path)
    comp = competence()
    before = comp.task_index
    pr = PracticeRound(tmp_path / 'p', comp, run_student=run)
    summary = pr.run(LIB, 4, label='r1')
    queue = [json.loads(l) for l in (tmp_path / 'p' / 'repair_queue.jsonl').read_text().splitlines()]
    assert len(queue) == 4 - summary['passed'] == 2
    assert all(q['skill_ids_called'] == ['count_log'] for q in queue)
    rounds = [json.loads(l) for l in (tmp_path / 'p' / 'practice_rounds.jsonl').read_text().splitlines()]
    assert rounds[0]['tasks'] == 4 and rounds[0]['passed'] == 2
    assert comp.task_index == before + 4 and comp.skills['count_log'].calls == 4


def test_no_targets_is_a_noop(tmp_path):
    run, seen = student(tmp_path)
    summary = PracticeRound(tmp_path / 'p', CompetenceModel(), run_student=run).run(LIB, 6)
    assert summary['tasks'] == 0 and seen == []


def test_practice_split_is_disjoint():
    assert split_of(13000) == 'practice' and split_of(16999) == 'practice'
    assert split_of(17000) == 'validation'          # W4-3 architect validation follows practice
    with pytest.raises(ValueError):
        split_of(19000)

import importlib.util
import json
from pathlib import Path

import pytest


def load():
    path = Path(__file__).resolve().parents[1] / 'scripts/experiments/stream_report.py'
    spec = importlib.util.spec_from_file_location('stream_report_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load()


def test_wilson_matches_hand_values():
    assert R.wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    assert R.wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert R.wilson(8, 20) == pytest.approx((0.2188, 0.6134), abs=1e-4)


def test_mcnemar_exact_matches_hand_values():
    assert R.mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert R.mcnemar_exact(1, 9) == pytest.approx(22 / 1024)
    assert R.mcnemar_exact(3, 3) == 1.0
    assert R.mcnemar_exact(0, 0) == 1.0


def write(root, name, rows):
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(''.join(json.dumps(r) + '\n' for r in rows))


def cp(label, task, family, score, negative=False, misuse=False):
    return {'checkpoint': label, 'task_id': task, 'family': family, 'score': score, 'negative': negative,
            'misuse': misuse, 'skill_calls': []}


def fake_arms(tmp_path):
    a0, a4, a5 = tmp_path / 'A0', tmp_path / 'A4', tmp_path / 'A5'
    tasks = [f'log-{i}' for i in range(4)]
    write(a0, 'checkpoints.jsonl', [cp('cp0', t, 'log_aggregation', 0.0) for t in tasks] +
          [cp('cp20', t, 'log_aggregation', 1.0 if i == 0 else 0.0) for i, t in enumerate(tasks)] +
          [cp('cp20', 'neg-0', 'read_preserve', 1.0, negative=True)])
    write(a4, 'checkpoints.jsonl', [cp('cp0', t, 'log_aggregation', 0.0) for t in tasks] +
          [cp('cp20', t, 'log_aggregation', 1.0) for t in tasks] +
          [cp('cp20', 'neg-0', 'read_preserve', 0.0, negative=True, misuse=True),
           cp('cp20', 'slug-0', 'text_normalize', 0.0)])
    stream = [{'index': i, 'task_id': f's{i}', 'family': 'log_aggregation', 'negative': False,
               'student_score': 0.0 if i < 2 else 1.0, 'solved_by_student': i >= 2, 'helped': i < 2,
               'learning': {'accepted': i == 1}} for i in range(12)]
    write(a4, 'stream.jsonl', stream)
    write(a4, 'spend.jsonl', [{'task_id': 's0', 'when': 'before', 'ledger_remaining_usd': 1.0},
                              {'task_id': 's0', 'when': 'after', 'ledger_remaining_usd': 0.99},
                              {'task_id': 's1', 'when': 'before', 'ledger_remaining_usd': 0.99},
                              {'task_id': 's1', 'when': 'after', 'ledger_remaining_usd': 0.97}])
    # A5: fails twice, asks before the 3rd, then a later miss that was not asked about
    write(a5, 'stream.jsonl', [
        {'index': 0, 'task_id': 'h0', 'family': 'f', 'student_score': 0.0, 'solved_by_student': False,
         'helped': True, 'help_decision': {'ask': False}},
        {'index': 1, 'task_id': 'h1', 'family': 'f', 'student_score': 0.0, 'solved_by_student': False,
         'helped': True, 'help_requested': True, 'help_decision': {'ask': False}},
        {'index': 2, 'task_id': 'h2', 'family': 'f', 'solved_by_student': False, 'helped': True,
         'help_decision': {'ask': True}},
        {'index': 3, 'task_id': 'h3', 'family': 'f', 'student_score': 0.0, 'solved_by_student': False,
         'helped': True, 'help_decision': {'ask': False}}])
    (a5 / 'competence.json').write_text(json.dumps({'help_log': [
        {'when': 'after_failure', 'asked': True}, {'when': 'student_requested', 'asked': True},
        {'when': 'before_attempt', 'asked': True}, {'when': 'after_failure', 'asked': True}]}))
    return a0, a4, a5


def test_report_from_fake_arms(tmp_path):
    a0, a4, a5 = fake_arms(tmp_path)
    out = tmp_path / 'report'
    R.main(['--arm-dir', f'A0={a0}', '--arm-dir', f'A4={a4}', '--arm-dir', f'A5={a5}', '--out', str(out)])
    summary = json.loads((out / 'summary.json').read_text())
    a4cp = summary['arms']['A4']['checkpoints']['cp20']
    assert a4cp['in_family']['k'] == 4 and a4cp['in_family']['n'] == 4
    assert a4cp['cross_family']['n'] == 1 and a4cp['misuse'] == {'k': 1, 'n': 1}
    pair = summary['paired']['A4 vs A0']['cp20']
    assert (pair['a_only'], pair['b_only'], pair['pairs']) == (3, 1, 5)
    assert pair['p'] == pytest.approx(R.mcnemar_exact(3, 1), abs=1e-6)
    blocks = summary['arms']['A4']['stream']
    assert blocks[0]['teacher_calls'] == 2 and blocks[0]['skills_accepted'] == 1
    assert blocks[0]['cloud_usd'] == pytest.approx(0.03) and blocks[1]['cumulative_cloud_usd'] == pytest.approx(0.03)
    report = (out / 'report.md').read_text()
    assert '| A4 | cp20 | 4/4' in report and 'A4 vs A0' in report


def test_help_quality_three_kinds_precision_and_misses(tmp_path):
    _, _, a5 = fake_arms(tmp_path)
    h = R.help_quality(R.load_arm([a5]))
    assert (h['before_attempt'], h['student_requested'], h['after_failure']) == (1, 1, 2)
    assert h['asked_before_tasks'] == 1 and h['precision_before'] == 1.0
    assert h['missed_asks'] == 2      # h0 and h3; h1 requested help itself


def test_missing_checkpoint_marked_no_data(tmp_path):
    empty = tmp_path / 'A1'
    empty.mkdir()
    out = tmp_path / 'r'
    R.main(['--arm-dir', f'A1={empty}', '--out', str(out)])
    assert '| A1 | 无数据 |' in (out / 'report.md').read_text()

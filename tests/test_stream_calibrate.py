import importlib.util
import json
from pathlib import Path

from core.evolution.stream_tasks import FAMILIES, split_of


def load():
    path = Path(__file__).resolve().parents[1] / 'scripts/experiments/stream_calibrate.py'
    spec = importlib.util.spec_from_file_location('stream_calibrate_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = load()


def test_all_seeds_in_calibration_split():
    tasks = C.calibration_tasks(list(FAMILIES), 10)
    assert len(tasks) == 10 * len(FAMILIES)
    assert all(split_of(t['seed']) == 'calibration' and t['split'] == 'calibration' for t in tasks)


def test_resume_skips_recorded_tasks(tmp_path):
    tasks = C.calibration_tasks(['log_aggregation'], 3)
    (tmp_path / 'results.jsonl').write_text(json.dumps(
        {'family': 'log_aggregation', 'seed': 5000, 'score': 1.0, 'status': 'passed', 'seconds': 1}) + '\n')
    ran = []

    def fake(task):
        ran.append(task['seed'])
        return 0.0, 'failed'
    summary = C.calibrate(tmp_path, tasks, fake)
    assert ran == [5001, 5002]
    assert summary['log_aggregation'] == {'passed': 1, 'total': 3, 'rate': 0.3333, 'negative': False, 'in_band': True}
    C.calibrate(tmp_path, tasks, fake)
    assert ran == [5001, 5002]


def test_band_judgement_and_negatives():
    rows = ([{'family': 'interval_merge', 'seed': s, 'score': 1.0} for s in range(6)] +
            [{'family': 'interval_merge', 'seed': s, 'score': 0.0} for s in range(6, 10)] +
            [{'family': 'csv_transform', 'seed': s, 'score': 0.0} for s in range(10)] +
            [{'family': 'subset_selection', 'seed': 0, 'score': 1.0}] +
            [{'family': 'subset_selection', 'seed': s, 'score': 0.0} for s in range(1, 10)] +
            [{'family': 'read_preserve', 'seed': s, 'score': 1.0} for s in range(10)])
    s = C.summarize(rows)
    assert s['interval_merge']['in_band'] is False        # 60% too easy
    assert s['csv_transform']['in_band'] is False         # 0% too hard
    assert s['subset_selection']['in_band'] is True       # 10% is inside the band
    assert s['read_preserve']['negative'] is True and 'in_band' not in s['read_preserve']


def test_crashed_rows_are_retried_and_not_counted(tmp_path):
    tasks = C.calibration_tasks(['interval_merge'], 2)
    (tmp_path / 'results.jsonl').write_text(
        json.dumps({'family': 'interval_merge', 'seed': 5000, 'score': 0.0, 'status': 'crashed', 'seconds': 0}) + '\n' +
        json.dumps({'family': 'interval_merge', 'seed': 5001, 'score': 1.0, 'status': 'passed', 'seconds': 9}) + '\n')
    ran = []

    def fake(task):
        ran.append(task['seed'])
        return 1.0, 'passed'
    summary = C.calibrate(tmp_path, tasks, fake)
    assert ran == [5000]
    assert summary['interval_merge']['passed'] == 2 and summary['interval_merge']['total'] == 2

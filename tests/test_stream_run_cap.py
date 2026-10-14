import importlib.util
from pathlib import Path


def load():
    path = Path(__file__).resolve().parents[1] / 'scripts/experiments/stream_run.py'
    spec = importlib.util.spec_from_file_location('stream_run_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_experiment_spend_is_shared_across_arms_and_not_reset(tmp_path):
    spend = load().experiment_spend
    cache = tmp_path / 'stream-slice' / 'teacher-cache'
    assert spend(cache, 0.98) == 0.0                 # first paid arm anchors the baseline
    assert round(spend(cache, 0.95), 6) == 0.03      # same arm later
    assert round(spend(cache, 0.90), 6) == 0.08      # second arm shares the allocation
    assert spend(cache, 0.99) == 0.0                 # never negative

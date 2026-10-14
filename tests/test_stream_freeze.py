import collections
import importlib.util
import json
from pathlib import Path

import pytest

from core.evolution.stream_tasks import split_of


def load(name):
    path = Path(__file__).resolve().parents[1] / f'scripts/experiments/{name}.py'
    spec = importlib.util.spec_from_file_location(f'{name}_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = load('stream_freeze')


def test_freeze_is_deterministic():
    assert {k: v['sha256'] for k, v in F.build().items()} == {k: v['sha256'] for k, v in F.build().items()}


def test_stream_composition_order_and_splits():
    built = F.build()
    for n in (1, 2):
        tasks = built[f'stream-seed{n}.json']['tasks']
        counts = collections.Counter(t['family'] for t in tasks)
        assert len(tasks) == 60
        assert all(counts[f] == 12 for f in F.CAPABILITY) and all(counts[f] == 4 for f in F.NEGATIVE)
        assert set(F.CAPABILITY) <= {t['family'] for t in tasks[:10]}
        assert all(t['split'] == 'stream' for t in tasks)
        assert all(int(t['task_id'].rsplit('-', 1)[1]) >= 1100 for t in tasks)    # E-0 instances excluded
    ev = built['eval.json']['tasks']
    counts = collections.Counter(t['family'] for t in ev)
    assert len(ev) == 48 and all(t['split'] == 'eval' for t in ev)
    assert all(counts[f] == 6 for f in F.CAPABILITY + F.CROSS) and all(counts[f] == 4 for f in F.NEGATIVE)
    assert all(split_of(int(t['task_id'].rsplit('-', 1)[1])) == 'eval' and
               not 9000 <= int(t['task_id'].rsplit('-', 1)[1]) < 9600 for t in ev)


def test_written_files_load_and_tampering_is_refused(tmp_path):
    F.main(['--out', str(tmp_path)])
    data = F.load(tmp_path / 'eval.json')
    assert data['sha256'] == F.build()['eval.json']['sha256']
    F.main(['--out', str(tmp_path)])                      # re-freezing the same content is a no-op
    text = (tmp_path / 'eval.json').read_text()
    (tmp_path / 'eval.json').write_text(text.replace('Save', 'Sav3', 1))
    with pytest.raises(ValueError):
        F.load(tmp_path / 'eval.json')


def test_stream_run_uses_frozen_manifests(tmp_path):
    F.main(['--out', str(tmp_path / 'm')])
    run = load('stream_run')
    root = tmp_path / 'A0'
    import sys
    argv = sys.argv
    sys.argv = ['stream_run.py', '--arm', 'A0', '--root', str(root), '--plan-only',
                '--stream-manifest', str(tmp_path / 'm' / 'stream-seed1.json'),
                '--eval-manifest', str(tmp_path / 'm' / 'eval.json'), '--checkpoints', '0,30,60']
    try:
        run.main()
    finally:
        sys.argv = argv
    config = json.loads((root / 'config.json').read_text())
    assert config['stream_tasks'] == 60 and config['eval_tasks'] == 48 and config['checkpoints'] == [0, 30, 60]
    assert config['stream_manifest'].endswith('stream-seed1.json')
    assert config['stream_sha256'] == json.loads((tmp_path / 'm' / 'stream-seed1.json').read_text())['sha256']

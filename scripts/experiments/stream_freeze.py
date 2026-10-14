"""Freeze Kage-Stream v1 manifests (W1-9): two learning streams and one shared eval set.

  python scripts/experiments/stream_freeze.py --out eval/stream_v1

Stream (per seed): F1-F4 x 12 + negatives 12 (read_preserve / inspect_question /
lookalike_readonly x 4), shuffled with Random('order:<n>') so that the first 10 tasks
contain every capability family (the first order seed that satisfies this is recorded).
Eval (shared): F1-F4 x 6 in-family, F5/F6 x 6 cross-family, negatives 3 x 4.

Seed ranges avoid every instance already exposed in the E-0 slice (stream 1000-1019,
eval 9000-9599). Once written and logged, these files are never edited; fixes go to v2.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.stream_tasks import manifest

CAPABILITY = ['subset_selection', 'interval_merge', 'log_aggregation', 'csv_transform']
CROSS = ['text_normalize', 'config_migrate']
NEGATIVE = ['read_preserve', 'inspect_question', 'lookalike_readonly']
STREAM_SEED_BASE = {1: 1100, 2: 2000}      # seed1 skips 1000-1099 (E-0 slice used 1000-1019)
EVAL_SEED_BASE = 10000                     # E-0 used 9000-9599


def stream_plan(stream_seed: int) -> tuple[list[tuple[str, int]], int]:
    base = STREAM_SEED_BASE[stream_seed]
    items = [(f, base + i) for f in CAPABILITY for i in range(12)]
    items += [(f, base + 100 + i) for f in NEGATIVE for i in range(4)]
    for order_seed in range(1000):
        shuffled = list(items)
        random.Random(f'order:{stream_seed}:{order_seed}').shuffle(shuffled)
        if set(CAPABILITY) <= {f for f, _ in shuffled[:10]}:
            return shuffled, order_seed
    raise RuntimeError('no order seed puts every capability family in the first 10 tasks')


def eval_plan() -> list[tuple[str, int]]:
    items = [(f, EVAL_SEED_BASE + i) for f in CAPABILITY + CROSS for i in range(6)]
    items += [(f, EVAL_SEED_BASE + 500 + i) for f in NEGATIVE for i in range(4)]
    return items


def build() -> dict[str, dict]:
    out = {}
    for n in (1, 2):
        items, order_seed = stream_plan(n)
        out[f'stream-seed{n}.json'] = {**manifest(items), 'role': 'stream', 'order_seed': order_seed}
    out['eval.json'] = {**manifest(eval_plan()), 'role': 'eval'}
    return out


def load(path: Path) -> dict:
    """Read a frozen manifest and refuse it unless its tasks still hash to the recorded sha256."""
    data = json.loads(Path(path).read_text())
    if manifest_sha(data['tasks']) != data['sha256']:
        raise ValueError(f'{path}: tasks do not match the frozen sha256')
    return data


def manifest_sha(tasks: list[dict]) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(tasks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, default=ROOT / 'eval/stream_v1')
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for name, data in build().items():
        path = args.out / name
        if path.exists():
            old = json.loads(path.read_text())
            if old['sha256'] != data['sha256']:
                p.error(f'{path} is frozen with a different sha256; write stream_v2 instead')
            print(name, old['sha256'], '(already frozen)')
            continue
        path.write_text(json.dumps({'created': created, **data}, ensure_ascii=False, indent=1))
        print(name, data['sha256'])


if __name__ == '__main__':
    main()

"""Freeze Kage-Stream web v1 manifests (C2): two browser learning streams and one shared eval set.

  python scripts/experiments/stream_web_freeze.py --out eval/stream_web_v1

Stream (per seed): web_invoice / web_prefs / web_catalog x 12 + web_lookup negatives x 8, shuffled
with Random('web-order:<n>:<k>') so that the first 8 tasks contain every learned family.
Eval (shared): the three learned families x 6 in-family, web_form x 6 cross-family (never in a
stream: does "reveal hidden rows first" carry over to "click Next before saving"?), web_lookup x 6.

Seeds come from the stream/eval splits and avoid the ranges of stream-v1 (stream 1000-2111,
eval 10000-10503 are file-family instances; family names differ, but the ranges stay disjoint
anyway). Once written and logged these files are never edited; fixes go to a v2.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.evolution.stream_tasks import manifest, split_of
from stream_freeze import load, manifest_sha  # noqa: F401  (re-exported for callers)

LEARN = ['web_invoice', 'web_prefs', 'web_catalog']
CROSS = ['web_form']
NEGATIVE = ['web_lookup']
STREAM_SEED_BASE = {1: 3000, 2: 3500}
EVAL_SEED_BASE = 11000


def stream_plan(stream_seed: int) -> tuple[list[tuple[str, int]], int]:
    base = STREAM_SEED_BASE[stream_seed]
    items = [(f, base + i) for f in LEARN for i in range(12)]
    items += [(f, base + 100 + i) for f in NEGATIVE for i in range(8)]
    for order_seed in range(1000):
        shuffled = list(items)
        random.Random(f'web-order:{stream_seed}:{order_seed}').shuffle(shuffled)
        if set(LEARN) <= {f for f, _ in shuffled[:8]}:
            return shuffled, order_seed
    raise RuntimeError('no order seed puts every learned family in the first 8 tasks')


def eval_plan() -> list[tuple[str, int]]:
    items = [(f, EVAL_SEED_BASE + i) for f in LEARN + CROSS for i in range(6)]
    items += [(f, EVAL_SEED_BASE + 500 + i) for f in NEGATIVE for i in range(6)]
    return items


def build() -> dict[str, dict]:
    out = {}
    for n in (1, 2):
        items, order_seed = stream_plan(n)
        assert all(split_of(s) == 'stream' for _, s in items)
        out[f'stream-seed{n}.json'] = {**manifest(items), 'suite_id': 'kage-stream-web-v1', 'role': 'stream',
                                       'order_seed': order_seed}
    items = eval_plan()
    assert all(split_of(s) == 'eval' for _, s in items)
    out['eval.json'] = {**manifest(items), 'suite_id': 'kage-stream-web-v1', 'role': 'eval'}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, default=ROOT / 'eval/stream_web_v1')
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for name, data in build().items():
        path = args.out / name
        if path.exists():
            old = json.loads(path.read_text())
            if old['sha256'] != data['sha256']:
                p.error(f'{path} is frozen with a different sha256; write stream_web_v2 instead')
            print(name, old['sha256'], '(already frozen)')
            continue
        path.write_text(json.dumps({'created': created, **data}, ensure_ascii=False, indent=1))
        print(name, data['sha256'])


if __name__ == '__main__':
    main()

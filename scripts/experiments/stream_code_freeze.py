"""Freeze the R4 round-2 eval set: the four code families a second round may learn (docs/plans/cards/R4.md).

  python scripts/experiments/stream_code_freeze.py [--out eval/stream_code_v1]

eval.json: 6 tasks per family at eval seeds 10000-10005 (the same seeds the stream-v1 capability families use; the v46
replay collection and any round-2 collection use practice seeds 13000+).
stream-seed1.json: the round-2 learning stream — 6 tasks per family at stream seeds 3000-3005 plus read-only negatives
(lookalike_readonly x 4, read_preserve x 2 at 3100+; stream-v1 used 1100-1203 and 2000-2103), shuffled once.
Never edited once written; fixes go to v2.
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
from core.evolution.code_tasks import ROUND2_FAMILIES      # noqa: E402
from core.evolution.stream_tasks import manifest           # noqa: E402

EVAL_SEED_BASE = 10000


STREAM_SEED_BASE = 3000


def build() -> dict[str, dict]:
    stream = [(family, STREAM_SEED_BASE + i) for family in ROUND2_FAMILIES for i in range(6)]
    stream += [('lookalike_readonly', STREAM_SEED_BASE + 100 + i) for i in range(4)]
    stream += [('read_preserve', STREAM_SEED_BASE + 100 + i) for i in range(2)]
    random.Random('order:code:1').shuffle(stream)
    return {'eval.json': {**manifest([(family, EVAL_SEED_BASE + i) for family in ROUND2_FAMILIES for i in range(6)]),
                          'role': 'eval'},
            'stream-seed1.json': {**manifest(stream), 'role': 'stream'}}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, default=ROOT / 'eval/stream_code_v1')
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for name, data in build().items():
        path = args.out / name
        if path.exists():
            if json.loads(path.read_text())['sha256'] != data['sha256']:
                p.error(f'{path} is frozen with a different sha256; write stream_code_v2 instead')
            print(name, data['sha256'], '(already frozen)')
            continue
        path.write_text(json.dumps({'created': created, **data}, ensure_ascii=False, indent=1))
        print(name, data['sha256'])

if __name__ == '__main__':
    main()

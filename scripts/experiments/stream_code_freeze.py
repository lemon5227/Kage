"""Freeze the R4 round-2 eval set: the four code families a second round may learn (docs/plans/cards/R4.md).

  python scripts/experiments/stream_code_freeze.py [--out eval/stream_code_v1]

Eval only: 6 tasks per family at eval seeds 10000-10005 (the same seeds the stream-v1 capability families use; the v46
replay collection and any round-2 collection use practice seeds 13000+). Never edited once written; fixes go to v2.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.code_tasks import ROUND2_FAMILIES      # noqa: E402
from core.evolution.stream_tasks import manifest           # noqa: E402

EVAL_SEED_BASE = 10000


def build() -> dict:
    return {**manifest([(family, EVAL_SEED_BASE + i) for family in ROUND2_FAMILIES for i in range(6)]), 'role': 'eval'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, default=ROOT / 'eval/stream_code_v1')
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    path, data = args.out / 'eval.json', build()
    if path.exists():
        if json.loads(path.read_text())['sha256'] != data['sha256']:
            p.error(f'{path} is frozen with a different sha256; write stream_code_v2 instead')
        print('eval.json', data['sha256'], '(already frozen)')
        return
    path.write_text(json.dumps({'created': datetime.datetime.now(datetime.timezone.utc).isoformat(), **data},
                               ensure_ascii=False, indent=1))
    print('eval.json', data['sha256'])


if __name__ == '__main__':
    main()

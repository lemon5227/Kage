"""R4 round-2 training data: the new families' guided-then-stripped samples mixed with replay of round 1.

  python scripts/experiments/r4_data.py --new evidence/reports/r4/sft-r3fg0.jsonl.gz \\
      --round1 <dir with the R3fg train.jsonl / val.jsonl> --out <dir> [--cap 300] [--lookalike 4]

Round 2 continues from the round-1 adapter's weights (docs/plans/cards/R4.md), so the data is what a continual learner
gets: every new-family sample (built like round 1: validated, de-duplicated, capped per family, read-back steps
inserted) plus as many round-1 rows again, sampled per family in proportion, plus every round-1 negative row, with
the lookalike_readonly rows repeated (the misuse seen in R3f/R3fg is on that family). Validation = the new families'
held-back tasks + round 1's validation rows. Deterministic for fixed inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import r3_data                                               # noqa: E402
from core.evolution.code_tasks import ROUND2_FAMILIES       # noqa: E402

SEED = 20261115


def build(new: Path, round1: Path, out: Path, cap: int = 300, lookalike: int = 4) -> dict:
    fresh = r3_data.build([new], out / 'new', cap=cap, readback=True)
    new_train, new_val = (r3_data.read_rows(out / 'new' / f'{name}.jsonl') for name in ('train', 'val'))
    other = sorted({row['family'] for row in new_train + new_val} - set(ROUND2_FAMILIES))
    if other:
        raise SystemExit(f'{new}: families outside round 2: {other}')
    old_train, old_val = (r3_data.read_rows(round1 / f'{name}.jsonl') for name in ('train', 'val'))
    negatives = [row for row in old_train if row.get('negative')]
    by_family: dict[str, list[dict]] = {}
    for row in old_train:
        if not row.get('negative'):
            by_family.setdefault(row['family'], []).append(row)
    pool = sum(len(rows) for rows in by_family.values())
    rng, replay = random.Random(SEED), []
    for family in sorted(by_family):
        rows = by_family[family]
        replay += rng.sample(rows, min(len(rows), round(len(new_train) * len(rows) / pool)))
    extra = [row for row in negatives if row['family'] == 'lookalike_readonly'] * (lookalike - 1)
    train = new_train + replay + negatives + extra
    val = new_val + old_val
    for name, rows in (('train', train), ('val', val)):
        with (out / f'{name}.jsonl').open('w') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    stats = {'new': {'path': str(new), 'sha256': r3_data.sha256_file(new), 'stats': fresh},
             'round1': {name: r3_data.sha256_file(round1 / f'{name}.jsonl') for name in ('train', 'val')},
             'cap': cap, 'lookalike_repeat': lookalike, 'sample_seed': SEED,
             'rows_out': {'train': len(train), 'val': len(val)},
             'parts': {'new': len(new_train), 'replay': len(replay), 'negatives': len(negatives),
                       'lookalike_extra': len(extra)},
             'rows': {'train': r3_data.family_counts(train), 'val': r3_data.family_counts(val)},
             'dropped': fresh['dropped'],
             'tasks': {'train': len({row['task_id'] for row in train}), 'val': len({row['task_id'] for row in val})},
             'sha256': {f'{name}.jsonl': r3_data.sha256_file(out / f'{name}.jsonl') for name in ('train', 'val')}}
    (out / 'data-stats.json').write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    return stats


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--new', type=Path, required=True)
    p.add_argument('--round1', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--cap', type=int, default=300)
    p.add_argument('--lookalike', type=int, default=4, help='how many times each round-1 lookalike_readonly row appears')
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    stats = build(args.new, args.round1, args.out, args.cap, args.lookalike)
    print(json.dumps({k: stats[k] for k in ('rows_out', 'parts', 'dropped')}))


if __name__ == '__main__':
    main()

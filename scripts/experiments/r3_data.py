"""R3 data: train/val splits from the R2 guidance-free samples, with leakage guards.

  python scripts/experiments/r3_data.py --sft FILE [--sft FILE ...] --out DIR \
      [--cap 600] [--val-frac 0.1]

Rows are in the R2 SFT format (task_id, family, negative, writes, tools, messages, target,
source, attempt, guidance). Transfer families and any seed outside the practice split are
refused outright; rows whose messages still mention guidance are dropped and counted.
Exact (messages, target) duplicates are dropped, each family keeps at most --cap rows
(uniform random subset, fixed seed), and the split is stratified by family over task_ids
(hash order), so every family with 2+ tasks is in both splits and no task straddles them.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.stream_tasks import split_of        # noqa: E402

TRANSFER_FAMILIES = ('text_normalize', 'config_migrate', 'web_form')
GUIDANCE_MARKERS = ('Lessons from earlier tasks', '[tool call] ', 'earlier page: pick the target_ref')
CAP_SEED = 0


def read_rows(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def seed_of(row: dict) -> int:
    return int(str(row['task_id']).rsplit('-', 1)[1])


def validate(rows: list[dict], source: Path) -> None:
    """Refuse transfer families and non-practice seeds: those must never be trained on."""
    problems = []
    for index, row in enumerate(rows, 1):
        family = row.get('family')
        if not isinstance(family, str) or not family:
            problems.append(f'{source}:{index}: row has no family')
            continue
        if family in TRANSFER_FAMILIES:
            problems.append(f'{source}:{index}: transfer family {family!r} must never be trained on')
            continue
        try:
            seed = seed_of(row)
        except (KeyError, IndexError, ValueError):
            problems.append(f'{source}:{index}: task_id {row.get("task_id")!r} has no numeric seed')
            continue
        try:
            split = split_of(seed)
        except ValueError:
            problems.append(f'{source}:{index}: seed {seed} is outside the registered splits')
            continue
        if split != 'practice':
            problems.append(f'{source}:{index}: {row["task_id"]} is in the {split} split, not practice')
    if problems:
        raise SystemExit('refusing to build R3 data:\n' + '\n'.join(problems))


def has_guidance(messages) -> bool:
    body = json.dumps(messages or [], ensure_ascii=False)
    return any(marker in body for marker in GUIDANCE_MARKERS)


def sample_key(messages, target) -> str:
    body = json.dumps([messages, target], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def family_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row['family']] = counts.get(row['family'], 0) + 1
    return dict(sorted(counts.items()))


def build(sft_paths: list[Path], out: Path, cap: int = 600, val_frac: float = 0.1,
          seed: int = CAP_SEED) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows, inputs = [], []
    for path in sft_paths:
        if not path.exists():
            raise SystemExit(f'missing input: {path}')
        loaded = read_rows(path)
        validate(loaded, path)
        inputs.append({'path': str(path), 'sha256': sha256_file(path), 'rows': len(loaded)})
        rows += loaded

    dropped = {'guidance_remnant': 0, 'duplicate': 0, 'cap': 0}
    kept, seen = [], set()
    for row in rows:
        if has_guidance(row.get('messages')):
            dropped['guidance_remnant'] += 1
            continue
        key = sample_key(row.get('messages'), row.get('target'))
        if key in seen:
            dropped['duplicate'] += 1
            continue
        seen.add(key)
        kept.append(row)

    by_family: dict[str, list[dict]] = {}
    for row in kept:
        by_family.setdefault(row['family'], []).append(row)
    rng = random.Random(seed)
    capped = []
    for family in sorted(by_family):
        family_rows = by_family[family]
        if len(family_rows) > cap:
            dropped['cap'] += len(family_rows) - cap
            family_rows = rng.sample(family_rows, cap)
        capped += family_rows

    # Stratified by family (v21 dry run: a plain hash split put a whole negative family into val and none of
    # web_prefs there). Per family, tasks are ordered by hash and the first round(val_frac * n) go to val;
    # a family with a single task stays in train. Rows of one task never straddle the split.
    val_tasks = set()
    tasks_by_family: dict[str, set] = {}
    for row in capped:
        tasks_by_family.setdefault(row['family'], set()).add(row['task_id'])
    for family, task_ids in tasks_by_family.items():
        ordered = sorted(task_ids, key=lambda task_id: hashlib.sha256(('r3-val-' + task_id).encode()).hexdigest())
        n_val = round(val_frac * len(ordered)) if len(ordered) >= 2 else 0
        if val_frac > 0 and len(ordered) >= 2:
            n_val = max(1, n_val)
        val_tasks.update(ordered[:n_val])
    splits = {'train': [], 'val': []}
    for row in capped:
        splits['val' if row['task_id'] in val_tasks else 'train'].append(row)
    for name in splits:
        splits[name].sort(key=lambda row: (row['family'], row['task_id'], int(row.get('attempt') or 0)))

    for name, split_rows in splits.items():
        with (out / f'{name}.jsonl').open('w') as handle:
            for row in split_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    stats = {
        'inputs': inputs,
        'cap': cap,
        'val_frac': val_frac,
        'cap_seed': seed,
        'rows_in': len(rows),
        'dropped': dropped,
        'rows_out': {name: len(split_rows) for name, split_rows in splits.items()},
        'rows': {name: family_counts(split_rows) for name, split_rows in splits.items()},
        'tasks': {name: len({row['task_id'] for row in split_rows}) for name, split_rows in splits.items()},
        'sha256': {f'{name}.jsonl': sha256_file(out / f'{name}.jsonl') for name in splits},
    }
    (out / 'data-stats.json').write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sft', type=Path, action='append', required=True, help='sft.jsonl or sft.jsonl.gz')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cap', type=int, default=600, help='maximum rows kept per family')
    parser.add_argument('--val-frac', type=float, default=0.1)
    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cap < 1:
        parser.error('--cap must be positive')
    if not 0.0 <= args.val_frac <= 1.0:
        parser.error('--val-frac must be between 0 and 1')
    stats = build(args.sft, args.out, args.cap, args.val_frac)
    print(json.dumps({key: stats[key] for key in ('rows_out', 'tasks', 'dropped')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

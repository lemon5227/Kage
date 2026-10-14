"""Kage-Stream v1: procedurally generated task families for learning-curve experiments.

Every instance is a plain task dict accepted by the existing EvolutionRunner/Evaluator:
``python_function`` criteria for capability tasks, ``read_preserve`` for negatives.
Hidden cases come from a reference implementation and never leave ``scoring_criteria``.

Seed ranges keep data uses apart (see SPLITS); an instance is fully determined by
(family, seed), so manifests can be frozen by hash before any model request.
"""
from __future__ import annotations

import copy
import hashlib
from itertools import combinations
import json
import random
from typing import Callable

SPLITS = {'stream': range(1000, 5000), 'calibration': range(5000, 9000), 'eval': range(9000, 13000)}


def split_of(seed: int) -> str:
    for name, seeds in SPLITS.items():
        if seed in seeds:
            return name
    raise ValueError(f'seed {seed} outside registered splits')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pick(rng, options):
    return options[rng.randrange(len(options))]


# ---------------------------------------------------------------- F3 log aggregation
_LEVELS = ['INFO', 'WARN', 'ERROR', 'DEBUG']
_SERVICES = ['auth', 'billing', 'search', 'mailer', 'gateway', 'cache', 'worker', 'ui']
_WORDS = ['started', 'timeout', 'retry', 'ok', 'failed', 'connected', 'closed', 'slow']


def _log_line(rng, *, lowercase_level=False):
    ts = f'2026-10-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00'
    level = _pick(rng, _LEVELS)
    level = level.lower() if lowercase_level else level
    return f'{ts} {level} {_pick(rng, _SERVICES)}: {" ".join(rng.choice(_WORDS) for _ in range(rng.randint(1, 3)))}'


def _parse(line):
    parts = line.split(' ', 3)
    if len(parts) < 4 or not parts[2].endswith(':') or len(parts[2]) < 2:
        return None
    return parts[1].upper(), parts[2][:-1]


def _log_reference(lines, key, only_levels):
    out = {}
    for line in lines:
        parsed = _parse(line) if isinstance(line, str) else None
        if parsed is None:
            continue
        level, service = parsed
        if only_levels and level not in only_levels:
            continue
        name = level if key == 'level' else service
        out[name] = out.get(name, 0) + 1
    return out


def log_aggregation(seed: int) -> dict:
    rng = random.Random(f'log_aggregation:{seed}')
    key = _pick(rng, ['level', 'service'])
    only = [] if key == 'level' else sorted(rng.sample(['WARN', 'ERROR'], rng.randint(1, 2)))
    fn = _pick(rng, ['summarize', 'tally_events', 'aggregate_log', 'count_entries', 'digest_lines'])
    file = _pick(rng, ['logstats.py', 'report.py', 'ops_summary.py', 'telemetry.py'])
    what = ('level' if key == 'level' else 'service') + ('' if not only else f' for levels {", ".join(only)} only')
    fmt = '"<timestamp> <LEVEL> <service>: <message>"'
    templates = [
        f'Implement {fn}(lines) in {file}. Each line looks like {fmt}. Return a dict mapping each {what} to how many lines it has. '
        'Levels are case-insensitive (report them upper-case). Skip malformed lines. Omit keys with zero count. Save {file}.',
        f'In {file}, {fn}(lines) should count log lines per {what}. Line format: {fmt}; level case may vary and must be upper-cased; '
        f'ignore lines that do not match. Return a plain dict of counts and save {file}.',
        f'Fix {file}: {fn}(lines) receives log strings formatted as {fmt}. Produce {{name: count}} per {what}, '
        f'treating level names case-insensitively (upper-case keys), dropping malformed input lines. Write the result to {file}.',
    ]
    instruction = _pick(rng, templates).replace('{file}', file)
    cases = []
    for _ in range(5):
        lines = [_log_line(rng, lowercase_level=rng.random() < 0.3) for _ in range(rng.randint(3, 9))]
        if rng.random() < 0.6:
            lines.insert(rng.randrange(len(lines) + 1), _pick(rng, ['', 'garbage', '2026-10-01 INFO', 'x y z']))
        cases.append({'args': [lines], 'expected': _log_reference(lines, key, only)})
    cases.append({'args': [[]], 'expected': {}})
    return {'family': 'log_aggregation', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(lines):\n    return {{}}\n', 'cases': cases,
            'params': {'key': key, 'only_levels': only}}


# ---------------------------------------------------------------- F1 subset selection
_IDS = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa']
_FIELDS = [('weight', 'value'), ('cost', 'gain'), ('size', 'score')]


def _subset_reference(items, capacity, wkey, vkey):
    if capacity < 0 or any(it[wkey] <= 0 for it in items):
        raise ValueError
    best = (-1, None)
    for r in range(len(items) + 1):
        for combo in combinations(items, r):
            if sum(it[wkey] for it in combo) <= capacity:
                value, ids = sum(it[vkey] for it in combo), sorted(it['id'] for it in combo)
                if value > best[0] or (value == best[0] and ids < best[1]):
                    best = (value, ids)
    return best[1]


def _subset_case(items, capacity, wkey, vkey, **extra):
    args = copy.deepcopy([items, capacity])
    try:
        return {'args': args, 'expected': _subset_reference(items, capacity, wkey, vkey), **extra}
    except ValueError:
        return {'args': args, 'raises': 'ValueError', **extra}


def subset_selection(seed: int) -> dict:
    rng = random.Random(f'subset_selection:{seed}')
    fn = _pick(rng, ['select_tasks', 'pick_jobs', 'choose', 'plan_batch', 'allocate'])
    file = _pick(rng, ['scheduler.py', 'selection.py', 'planner.py', 'batch.py'])
    wkey, vkey = _pick(rng, _FIELDS)
    noun = _pick(rng, ['jobs', 'projects', 'parcels'])
    rules = (f'Each item is a dict with a unique string "id", a positive integer "{wkey}" and a non-negative integer "{vkey}". '
             f'Return the sorted list of ids whose total {vkey} is as large as possible while total {wkey} stays <= capacity. '
             f'If several selections tie on total {vkey}, return the lexicographically smallest sorted id list. '
             f'An empty selection is allowed. Raise ValueError if capacity is negative or any {wkey} is <= 0. '
             'Do not modify the input.')
    templates = [
        f'Implement {fn}(items, capacity) in {file} to choose {noun}. {rules} Save {file}.',
        f'In {file}, write {fn}(items, capacity) that picks which {noun} to take. {rules} Save the file {file}.',
        f'Fix {file}: {fn}(items, capacity) must select {noun} under a capacity limit. {rules} Write the result to {file}.',
    ]
    instruction = _pick(rng, templates)
    cases = []
    for _ in range(5):
        ids = rng.sample(_IDS, rng.randint(2, 8))
        items = [{'id': i, wkey: rng.randint(1, 6), vkey: rng.randint(0, 12)} for i in ids]
        cases.append(_subset_case(items, rng.randint(0, 15), wkey, vkey))
    cases.append(_subset_case([], 0, wkey, vkey))
    cases.append(_subset_case([], -1, wkey, vkey))
    zero = rng.sample(_IDS, 2)
    cases.append(_subset_case([{'id': zero[0], wkey: 0, vkey: 3}, {'id': zero[1], wkey: 2, vkey: 1}], 5, wkey, vkey))
    pair, w, v = sorted(rng.sample(_IDS, 2), reverse=True), rng.randint(1, 6), rng.randint(1, 12)
    cases.append(_subset_case([{'id': pair[0], wkey: w, vkey: v}, {'id': pair[1], wkey: w, vkey: v}], w, wkey, vkey,
                              tie=True))
    return {'family': 'subset_selection', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(items, capacity):\n    return None\n', 'cases': cases,
            'params': {'wkey': wkey, 'vkey': vkey}}


# ---------------------------------------------------------------- negatives (must not modify)
_NEG_BODIES = [
    'def clamp(value, low, high):\n    if low > high:\n        raise ValueError("low > high")\n    return max(low, min(high, value))\n',
    'def slug(text):\n    return "-".join(text.lower().split())\n',
    'def mean(xs):\n    if not xs:\n        raise ValueError("empty")\n    return sum(xs) / len(xs)\n',
]
_NEG_TEXT = ['release notes\n- fixed login\n- faster search\n', '2026-10-01T00:00:00 INFO auth: started\n']


def read_preserve(seed: int) -> dict:
    rng = random.Random(f'read_preserve:{seed}')
    if rng.random() < 0.7:
        content = _pick(rng, _NEG_BODIES)
        file = _pick(rng, ['helpers.py', 'utils.py', 'mathx.py', 'textops.py'])
    else:
        content = _pick(rng, _NEG_TEXT)
        file = _pick(rng, ['NOTES.txt', 'events.log', 'CHANGELOG.md'])
    instruction = _pick(rng, [
        f'Read {file} and tell me in one sentence what it contains. Do not change any file.',
        f'Please look at {file} and summarize it. It is already correct; leave it exactly as it is.',
        f'What is in {file}? Just read it and answer; no edits are needed.',
    ])
    return {'family': 'read_preserve', 'instruction': instruction, 'file': file, 'initial_text': content,
            'params': {}}


FAMILIES: dict[str, Callable[[int], dict]] = {
    'log_aggregation': log_aggregation,
    'subset_selection': subset_selection,
    'read_preserve': read_preserve,
}
NEGATIVE_FAMILIES = {'read_preserve'}


def make_task(family: str, seed: int) -> dict:
    """Task dict in the runner's format; split derived from the seed range."""
    spec = FAMILIES[family](seed)
    split = split_of(seed)
    task_id = f'stream-v1-{family}-{seed}'
    if family in NEGATIVE_FAMILIES:
        text = spec['initial_text']
        return {'task_id': task_id, 'family': family, 'split': split, 'instruction': spec['instruction'],
                'initial_files': {spec['file']: text}, 'expected_output_file': spec['file'],
                'scoring_criteria': {'type': 'read_preserve', 'file': spec['file'], 'sha256': _sha(text)},
                'negative': True}
    return {'task_id': task_id, 'family': family, 'split': split, 'instruction': spec['instruction'],
            'initial_files': {spec['file']: spec['initial_source']}, 'expected_output_file': spec['file'],
            'scoring_criteria': {'type': 'python_function', 'file': spec['file'], 'function': spec['function'],
                                 'cases': spec['cases']},
            'negative': False}


def manifest(families_seeds: list[tuple[str, int]]) -> dict:
    tasks = [make_task(f, s) for f, s in families_seeds]
    body = json.dumps(tasks, sort_keys=True, ensure_ascii=False)
    return {'suite_id': 'kage-stream-v1', 'sha256': _sha(body), 'tasks': tasks}


def public_view(task: dict) -> dict:
    """What a student or teacher may see: never the hidden cases or hashes."""
    return {k: task[k] for k in ('task_id', 'family', 'instruction', 'initial_files', 'expected_output_file') if k in task}

"""Kage-Stream v1: procedurally generated task families for learning-curve experiments.

Every instance is a plain task dict accepted by the existing EvolutionRunner/Evaluator:
``python_function`` criteria for capability tasks, ``read_preserve`` for negatives.
Hidden cases come from a reference implementation and never leave ``scoring_criteria``.

Seed ranges keep data uses apart (see SPLITS); an instance is fully determined by
(family, seed), so manifests can be frozen by hash before any model request.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
from itertools import combinations
import json
import random
import re
from typing import Callable
import unicodedata

SPLITS = {'stream': range(1000, 5000), 'calibration': range(5000, 9000), 'eval': range(9000, 13000),
          'practice': range(13000, 17000)}


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


# ---------------------------------------------------------------- F2 interval merge
_INTERVAL_KEYS = [('start', 'end'), ('begin', 'finish'), ('from', 'to')]


def _interval_reference(intervals, rep, keys, touching):
    pairs = [(iv[0], iv[1]) if rep == 'pair' else (iv[keys[0]], iv[keys[1]]) for iv in intervals]
    if any(s > e for s, e in pairs):
        raise ValueError
    merged = []
    for s, e in sorted(pairs):
        if merged and (s < merged[-1][1] or (touching and s == merged[-1][1])):
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged if rep == 'pair' else [{keys[0]: s, keys[1]: e} for s, e in merged]


def interval_merge(seed: int) -> dict:
    rng = random.Random(f'interval_merge:{seed}')
    fn = _pick(rng, ['merge_slots', 'combine_ranges', 'coalesce', 'merge_bookings'])
    file = _pick(rng, ['calendar_ops.py', 'ranges.py', 'booking.py'])
    rep = _pick(rng, ['pair', 'dict'])
    keys = list(_pick(rng, _INTERVAL_KEYS))
    touching = rng.random() < 0.5
    if rep == 'pair':
        shape = 'Each interval is a two-element list [start, end] of integers'
        out = 'Return merged intervals in the same [start, end] list form'
    else:
        shape = f'Each interval is a dict {{"{keys[0]}": s, "{keys[1]}": e}} with integer values'
        out = f'Return merged intervals as dicts with the same "{keys[0]}"/"{keys[1]}" keys'
    touch = ('Touching intervals like [1,3] and [3,5] should be merged.' if touching
             else 'Touching intervals like [1,3] and [3,5] should not be merged; only real overlaps merge.')
    rules = (f'{shape}. {out}, sorted by start ascending. {touch} '
             'Raise ValueError if any interval has start > end. Do not modify the input.')
    templates = [
        f'Implement {fn}(intervals) in {file} to merge overlapping intervals. {rules} Save {file}.',
        f'In {file}, write {fn}(intervals) that combines overlapping time ranges. {rules} Save the file {file}.',
        f'Fix {file}: {fn}(intervals) must merge overlapping bookings. {rules} Write the result to {file}.',
    ]
    instruction = _pick(rng, templates)

    def encode(pairs):
        return [list(p) if rep == 'pair' else {keys[0]: p[0], keys[1]: p[1]} for p in pairs]

    def case(pairs, **extra):
        args = copy.deepcopy([encode(pairs)])
        try:
            return {'args': args, 'expected': _interval_reference(args[0], rep, keys, touching), **extra}
        except ValueError:
            return {'args': args, 'raises': 'ValueError', **extra}

    cases = []
    for _ in range(5):
        pairs = []
        for _ in range(rng.randint(1, 7)):
            s = rng.randint(0, 20)
            pairs.append((s, s + rng.randint(0, 6)))
        rng.shuffle(pairs)
        cases.append(case(pairs))
    cases.append(case([]))
    a = rng.randint(0, 10)
    cases.append(case([(a + 4, a + 1)]))
    cases.append(case([(a + 3, a + 6), (a, a + 3)], touching_case=True))
    cases.append(case([(a + 1, a + 2), (a, a + 9)]))
    return {'family': 'interval_merge', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(intervals):\n    return None\n', 'cases': cases,
            'params': {'rep': rep, 'keys': keys, 'touching': touching}}


# ---------------------------------------------------------------- F4 CSV transform
_CSV_COLUMNS = ['id', 'name', 'email', 'city', 'team', 'score']
_CSV_VALUES = {
    'id': lambda rng: f'{rng.randint(1, 40):03d}',
    'name': lambda rng: _pick(rng, ['Ann Lee', 'Bo Chen', 'Cy Park', 'Di Wu', 'Ed Kim', 'Fa Li']),
    'email': lambda rng: _pick(rng, ['Ann@Example.com', 'bo@mail.org', 'CY@corp.io', 'di@Mail.org', 'ed@x.net']),
    'city': lambda rng: _pick(rng, ['Paris', 'Oslo', 'Lima, PE', 'Rome', 'Kyiv']),
    'team': lambda rng: _pick(rng, ['red', 'blue', 'green', 'ops']),
    'score': lambda rng: str(rng.randint(0, 99)),
}


def _csv_reference(text, key, required, email, sort_col):
    if text == '':
        return ''
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    idx = {name: i for i, name in enumerate(header)}
    out, seen = [], set()
    for row in body:
        row = [cell.strip() for cell in row]
        if not row[idx[required]]:
            continue
        if email:
            row[idx[email]] = row[idx[email]].lower()
        if row[idx[key]] in seen:
            continue
        seen.add(row[idx[key]])
        out.append(row)
    out.sort(key=lambda r: r[idx[sort_col]])
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(out)
    return buf.getvalue()


def _csv_text(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def csv_transform(seed: int) -> dict:
    rng = random.Random(f'csv_transform:{seed}')
    fn = _pick(rng, ['clean_rows', 'tidy_csv', 'normalize_table', 'dedupe_export'])
    file = _pick(rng, ['export_clean.py', 'table_ops.py', 'crm_clean.py'])
    has_email = rng.random() < 0.5
    pool = [c for c in _CSV_COLUMNS if c != 'email']
    cols = rng.sample(pool, rng.randint(3, 4) if has_email else rng.randint(3, 5))
    if has_email:
        cols.insert(rng.randrange(len(cols) + 1), 'email')
    key, required, sort_col = _pick(rng, cols), _pick(rng, cols), _pick(rng, cols)
    email = 'email' if has_email else None
    steps = (f'The input is CSV text with a header row (columns: {", ".join(cols)}). Return cleaned CSV text with the same header. '
             f'In order: strip leading/trailing whitespace from every cell; drop rows whose "{required}" cell is empty; '
             + (f'lower-case the "{email}" column; ' if email else '')
             + f'remove duplicate rows by "{key}", keeping the first occurrence; sort rows by "{sort_col}" ascending as strings '
             "(stable). Write the output with the csv module using '\\n' line endings. An empty string returns ''; "
             'a header-only input returns just the header line.')
    templates = [
        f'Implement {fn}(text) in {file}. {steps} Save {file}.',
        f'In {file}, write {fn}(text) to clean an exported table. {steps} Save the file {file}.',
        f'Fix {file}: {fn}(text) should tidy a CSV export. {steps} Write the result to {file}.',
    ]
    instruction = _pick(rng, templates)
    cases = []
    for _ in range(5):
        rows = []
        for _ in range(rng.randint(3, 9)):
            row = [_CSV_VALUES[c](rng) for c in cols]
            if rng.random() < 0.2:
                row[cols.index(required)] = ''
            rows.append(row)
        if rows and rng.random() < 0.8:
            dup = list(rng.choice(rows))
            dup[cols.index(key)] = ' ' + dup[cols.index(key)] + ' '
            rows.insert(rng.randrange(len(rows) + 1), dup)
        rows = [[(' ' + c if rng.random() < 0.2 else c) + (' ' if rng.random() < 0.2 else '') for c in r] for r in rows]
        text = _csv_text(cols, rows)
        cases.append({'args': [text], 'expected': _csv_reference(text, key, required, email, sort_col)})
    cases.append({'args': [''], 'expected': ''})
    header_only = _csv_text(cols, [])
    cases.append({'args': [header_only], 'expected': _csv_reference(header_only, key, required, email, sort_col)})
    comma_row = [_CSV_VALUES[c](rng) for c in cols]
    comma_row[cols.index(sort_col)] = 'Lima, PE'
    comma_row[cols.index(required)] = comma_row[cols.index(required)] or 'x'
    comma = _csv_text(cols, [comma_row])
    cases.append({'args': [comma], 'expected': _csv_reference(comma, key, required, email, sort_col)})
    return {'family': 'csv_transform', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(text):\n    return None\n', 'cases': cases,
            'params': {'key': key, 'required': required, 'email': email, 'sort_col': sort_col, 'columns': cols}}


# ---------------------------------------------------------------- F5 text normalize (eval only)
_SLUG_INPUTS = ['Café Déjà Vu', 'Hello, World!', '  Spaces   everywhere ', 'Q3 Report (final) v2', 'naïve résumé',
                'Über-Cool_Project', 'a/b\\c:d', 'MiXeD CaSe 42', 'Ünïcödé Tëxt', 'end---dash']


def _normalize_reference(text, sep, max_len):
    if not isinstance(text, str):
        raise TypeError
    ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', sep, ascii_text.lower()).strip(sep)
    if max_len is not None:
        slug = slug[:max_len].rstrip(sep)
    return slug


def text_normalize(seed: int) -> dict:
    rng = random.Random(f'text_normalize:{seed}')
    fn = _pick(rng, ['slugify', 'make_handle', 'to_key', 'label_id'])
    file = _pick(rng, ['slugs.py', 'naming.py', 'labels.py'])
    sep = _pick(rng, ['-', '_'])
    max_len = None if rng.random() < 0.5 else rng.randint(8, 24)
    limit = (f'If the result is longer than {max_len} characters, cut it to {max_len} and then strip a trailing "{sep}". '
             if max_len else '')
    rules = ('Apply unicodedata NFKD normalization and drop non-ASCII characters; lower-case; replace every run of characters '
             f'outside [a-z0-9] with a single "{sep}"; strip leading and trailing "{sep}". {limit}'
             'Raise TypeError for non-string input.')
    templates = [
        f'Implement {fn}(text) in {file} to build a URL slug. {rules} Save {file}.',
        f'In {file}, write {fn}(text) that turns a title into a handle. {rules} Save the file {file}.',
        f'Fix {file}: {fn}(text) must normalize labels into identifiers. {rules} Write the result to {file}.',
    ]
    instruction = _pick(rng, templates)
    cases = [{'args': [t], 'expected': _normalize_reference(t, sep, max_len)} for t in rng.sample(_SLUG_INPUTS, 5)]
    cases.append({'args': [''], 'expected': ''})
    cases.append({'args': ['---'], 'expected': ''})
    cases.append({'args': [None], 'raises': 'TypeError'})
    if max_len:
        # a word boundary exactly at the cut: the separator lands on position max_len
        cut = 'a' * max_len + ' tail'
        cases.append({'args': [cut], 'expected': _normalize_reference(cut, sep, max_len)})
        edge = 'b' * (max_len - 1) + ' tail'
        cases.append({'args': [edge], 'expected': _normalize_reference(edge, sep, max_len), 'cut_on_separator': True})
    return {'family': 'text_normalize', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(text):\n    return None\n', 'cases': cases,
            'params': {'sep': sep, 'max_len': max_len}}


# ---------------------------------------------------------------- F6 config migrate (eval only)
_RENAMES = [('host', 'hostname'), ('user', 'username'), ('pwd_file', 'password_file'), ('dir', 'directory'),
            ('max_conn', 'max_connections')]
_GROUPABLE = ['port', 'retries', 'cache_size', 'workers', 'region']
_CFG_VALUES = {'host': 'db.local', 'user': 'kage', 'pwd_file': '/run/pw', 'dir': '/var/data', 'max_conn': 32,
               'port': 5432, 'retries': 3, 'cache_size': 256, 'workers': 4, 'region': 'eu-west'}


def _migrate_reference(cfg, renames, grouped, section):
    if cfg.get('version') != 1:
        raise ValueError
    out, group = {'version': 2}, {}
    for key, value in cfg.items():
        if key == 'version' or value is None:
            continue
        if key == 'timeout_ms':
            out['timeout_s'] = value / 1000
        elif key in grouped:
            group[key] = value
        else:
            out[renames.get(key, key)] = value
    out[section] = group
    return out


def config_migrate(seed: int) -> dict:
    rng = random.Random(f'config_migrate:{seed}')
    fn = _pick(rng, ['migrate', 'upgrade_config', 'to_v2', 'convert_settings'])
    file = _pick(rng, ['settings_migration.py', 'config_v2.py', 'upgrade.py'])
    renames = dict(rng.sample(_RENAMES, rng.randint(2, 3)))
    grouped = sorted(rng.sample(_GROUPABLE, 2))
    section = _pick(rng, ['network', 'storage', 'limits'])
    rename_text = ', '.join(f'"{a}" -> "{b}"' for a, b in renames.items())
    rules = (f'Return a new dict and do not modify the input. Raise ValueError unless cfg.get("version") == 1. '
             f'The output has "version": 2. Rename top-level keys {rename_text}. Move "{grouped[0]}" and "{grouped[1]}" '
             f'into a sub-dict "{section}" (always present, possibly empty). If "timeout_ms" exists, output '
             '"timeout_s" = timeout_ms / 1000 (a float) instead. Keep other keys unchanged and drop keys whose value is None.')
    templates = [
        f'Implement {fn}(cfg) in {file} to migrate a v1 config dict to v2. {rules} Save {file}.',
        f'In {file}, write {fn}(cfg) that upgrades settings from version 1 to 2. {rules} Save the file {file}.',
        f'Fix {file}: {fn}(cfg) must convert old configuration dicts to the v2 layout. {rules} Write the result to {file}.',
    ]
    instruction = _pick(rng, templates)
    cases = []
    for _ in range(5):
        keys = rng.sample(list(_CFG_VALUES), rng.randint(3, 6))
        cfg = {'version': 1, **{k: _CFG_VALUES[k] for k in keys}}
        if rng.random() < 0.7:
            cfg['timeout_ms'] = rng.choice([250, 1500, 30000])
        cfg[_pick(rng, ['debug', 'label', 'owner'])] = _pick(rng, [True, 'svc', 7])
        cfg[_pick(rng, ['proxy', 'notes'])] = None
        cases.append({'args': [cfg], 'expected': _migrate_reference(cfg, renames, grouped, section)})
    cases.append({'args': [{'version': 2}], 'raises': 'ValueError'})
    cases.append({'args': [{}], 'raises': 'ValueError'})
    cases.append({'args': [{'version': 1}], 'expected': {'version': 2, section: {}}})
    return {'family': 'config_migrate', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(cfg):\n    return None\n', 'cases': cases,
            'params': {'renames': renames, 'grouped': grouped, 'section': section}}


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



_EXTRA_BODIES = [
    'def is_even(n):\n    return n % 2 == 0\n\n\ndef is_odd(n):\n    return not is_even(n)\n',
    'def parse_port(text):\n    port = int(text)\n    if not 0 < port < 65536:\n        raise ValueError("port out of range")\n    return port\n',
    'def chunks(xs, size):\n    if size <= 0:\n        raise ValueError("size must be positive")\n    return [xs[i:i + size] for i in range(0, len(xs), size)]\n',
]


def inspect_question(seed: int) -> dict:
    rng = random.Random(f'inspect_question:{seed}')
    content = _pick(rng, _NEG_BODIES + _EXTRA_BODIES)
    file = _pick(rng, ['helpers.py', 'utils.py', 'mathx.py', 'textops.py', 'checks.py'])
    instruction = _pick(rng, [
        f'How many functions are defined in {file}? Answer in one line; do not edit any file.',
        f'Which exception, if any, does the code in {file} raise for invalid input? Just answer, no changes.',
        f'Look at {file} and tell me the name of each function it defines. Do not modify anything.',
    ])
    return {'family': 'inspect_question', 'instruction': instruction, 'file': file, 'initial_text': content,
            'params': {}}


_LOOKALIKE_SOURCES = {
    'log_aggregation': lambda spec: (
        f"def {spec['function']}(lines):\n    key, only = {spec['params']['key']!r}, {spec['params']['only_levels']!r}\n"
        "    out = {}\n    for line in lines:\n        if not isinstance(line, str):\n            continue\n"
        "        parts = line.split(' ', 3)\n"
        "        if len(parts) < 4 or not parts[2].endswith(':') or len(parts[2]) < 2:\n            continue\n"
        "        level, service = parts[1].upper(), parts[2][:-1]\n"
        "        if only and level not in only:\n            continue\n"
        "        name = level if key == 'level' else service\n        out[name] = out.get(name, 0) + 1\n"
        "    return out\n"),
    'interval_merge': lambda spec: (
        f"def {spec['function']}(intervals):\n"
        f"    rep, keys, touching = {spec['params']['rep']!r}, {spec['params']['keys']!r}, {spec['params']['touching']!r}\n"
        "    pairs = [(iv[0], iv[1]) if rep == 'pair' else (iv[keys[0]], iv[keys[1]]) for iv in intervals]\n"
        "    if any(s > e for s, e in pairs):\n        raise ValueError('start > end')\n    merged = []\n"
        "    for s, e in sorted(pairs):\n"
        "        if merged and (s < merged[-1][1] or (touching and s == merged[-1][1])):\n"
        "            merged[-1][1] = max(merged[-1][1], e)\n        else:\n            merged.append([s, e])\n"
        "    return merged if rep == 'pair' else [{keys[0]: s, keys[1]: e} for s, e in merged]\n"),
    'subset_selection': lambda spec: (
        "from itertools import combinations\n\n\n"
        f"def {spec['function']}(items, capacity):\n"
        f"    wkey, vkey = {spec['params']['wkey']!r}, {spec['params']['vkey']!r}\n"
        "    if capacity < 0 or any(it[wkey] <= 0 for it in items):\n        raise ValueError('invalid input')\n"
        "    best = (-1, None)\n    for r in range(len(items) + 1):\n        for combo in combinations(items, r):\n"
        "            if sum(it[wkey] for it in combo) <= capacity:\n"
        "                value, ids = sum(it[vkey] for it in combo), sorted(it['id'] for it in combo)\n"
        "                if value > best[0] or (value == best[0] and ids < best[1]):\n"
        "                    best = (value, ids)\n    return best[1]\n"),
}


def lookalike_readonly(seed: int) -> dict:
    """A file that already solves a learning-stream family: reviewing it must not rewrite it."""
    rng = random.Random(f'lookalike_readonly:{seed}')
    family = _pick(rng, sorted(_LOOKALIKE_SOURCES))
    spec = FAMILIES[family](seed)
    content = _LOOKALIKE_SOURCES[family](spec)
    file, fn = spec['file'], spec['function']
    instruction = _pick(rng, [
        f'Review {fn} in {file} and explain in two sentences what it does. It is already correct. Do not modify it.',
        f'Can you explain how {file} implements {fn}? It is already correct. Do not modify it.',
        f'Read {file} and describe the edge cases {fn} handles. It is already correct. Do not modify it.',
    ])
    return {'family': 'lookalike_readonly', 'instruction': instruction, 'file': file, 'initial_text': content,
            'params': {'source_family': family, 'function': fn}}


FAMILIES: dict[str, Callable[[int], dict]] = {
    'log_aggregation': log_aggregation,
    'subset_selection': subset_selection,
    'interval_merge': interval_merge,
    'csv_transform': csv_transform,
    'text_normalize': text_normalize,
    'config_migrate': config_migrate,
    'read_preserve': read_preserve,
    'inspect_question': inspect_question,
    'lookalike_readonly': lookalike_readonly,
}
NEGATIVE_FAMILIES = {'read_preserve', 'inspect_question', 'lookalike_readonly'}


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

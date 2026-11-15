"""Code-writing families for self-distilled replay (R3f, docs/plans/r3f-forgetting-fix.md).

R3 forgot how to write code outside the four learned families, and its replay (AgentNet desktop text, Toucan MCP calls)
held no code at all. R3f replays the frozen student's own passing solutions to *other* programming tasks. These four
families exist only for that: they are none of the learned families (subset_selection, interval_merge, log_aggregation,
csv_transform), none of the held-out ones (text_normalize, config_migrate), and never in any eval manifest. Same task
shape as stream_tasks (python_function checker, hidden cases from a reference implementation, seed-determined).
"""
from __future__ import annotations

import copy
import random


def _pick(rng, options):
    return options[rng.randrange(len(options))]


def _templates(fn, args, file, goal, rules):
    return [
        f'Implement {fn}({args}) in {file} to {goal}. {rules} Save {file}.',
        f'In {file}, write {fn}({args}) that should {goal}. {rules} Save the file {file}.',
        f'Fix {file}: {fn}({args}) must {goal}. {rules} Write the result to {file}.',
    ]


def _case(reference, args, **extra):
    args = copy.deepcopy(args)
    try:
        return {'args': args, 'expected': reference(*copy.deepcopy(args)), **extra}
    except (ValueError, ZeroDivisionError) as exc:
        return {'args': args, 'raises': type(exc).__name__, **extra}


# ---------------------------------------------------------------- R1 reverse Polish notation
def _rpn_reference(expr, ops, floor_div):
    stack = []
    for token in expr.split():
        if token in ops:
            if len(stack) < 2:
                raise ValueError('not enough operands')
            b, a = stack.pop(), stack.pop()
            if token == '+':
                stack.append(a + b)
            elif token == '-':
                stack.append(a - b)
            elif token == '*':
                stack.append(a * b)
            else:
                if b == 0:
                    raise ZeroDivisionError('division by zero')
                stack.append(a // b if floor_div else int(a / b))
        else:
            try:
                stack.append(int(token))
            except ValueError:
                raise ValueError(f'bad token {token!r}') from None
    if len(stack) != 1:
        raise ValueError('malformed expression')
    return stack[0]


def rpn_eval(seed: int) -> dict:
    rng = random.Random(f'rpn_eval:{seed}')
    fn = _pick(rng, ['evaluate', 'calc_rpn', 'run_postfix', 'eval_stack'])
    file = _pick(rng, ['rpn.py', 'postfix.py', 'stack_calc.py'])
    ops = _pick(rng, ['+-*', '+-*/'])
    floor_div = rng.random() < 0.5
    div = ('' if '/' not in ops else
           ('"/" is integer floor division (like Python //). ' if floor_div
            else '"/" is integer division truncated toward zero (so -7 / 2 is -3). ')
           + 'Dividing by zero raises ZeroDivisionError. ')
    rules = (f'The expression is a string of space-separated tokens in reverse Polish notation: integers (possibly '
             f'negative, like -4) and the operators {" ".join(ops)}. {div}Return the integer result. Raise ValueError '
             'for an unknown token, an operator without two operands, or anything other than exactly one value left.')
    instruction = _pick(rng, _templates(fn, 'expr', file, 'evaluate a postfix expression', rules))

    def ref(expr):
        return _rpn_reference(expr, ops, floor_div)

    def random_expr(depth):
        if depth == 0 or rng.random() < 0.3:
            return str(rng.randint(-9, 20))
        return f'{random_expr(depth - 1)} {random_expr(depth - 1)} {_pick(rng, ops)}'

    cases = [_case(ref, [random_expr(3)]) for _ in range(5)]
    cases += [_case(ref, ['7']), _case(ref, ['1 +']), _case(ref, ['2 3']), _case(ref, ['4 x +'])]
    if '/' in ops:
        cases += [_case(ref, ['-7 2 /'], division=True), _case(ref, ['5 0 /'])]
    return {'family': 'rpn_eval', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(expr):\n    return None\n', 'cases': cases,
            'params': {'ops': ops, 'floor_div': floor_div}}


# ---------------------------------------------------------------- R2 run-length encoding
def _rle_reference(text, count_first, keep_ones):
    if any(ch.isdigit() for ch in text):
        raise ValueError('digits cannot be encoded')
    out, i = [], 0
    while i < len(text):
        j = i
        while j < len(text) and text[j] == text[i]:
            j += 1
        n = j - i
        count = '' if n == 1 and not keep_ones else str(n)
        out.append(count + text[i] if count_first else text[i] + count)
        i = j
    return ''.join(out)


_RLE_ALPHABET = 'aaabbbcczz  .-'


def run_length(seed: int) -> dict:
    rng = random.Random(f'run_length:{seed}')
    fn = _pick(rng, ['rle_encode', 'compress_runs', 'pack_text', 'encode_runs'])
    file = _pick(rng, ['rle.py', 'packing.py', 'runs.py'])
    count_first = rng.random() < 0.5
    keep_ones = rng.random() < 0.5
    form = '"3a" (count before the character)' if count_first else '"a3" (character before the count)'
    ones = ('A run of length 1 is written with its count 1 too.' if keep_ones
            else 'A run of length 1 is written as the bare character, without a count.')
    rules = (f'Replace every run of the same character with one group written as {form}. {ones} Spaces and punctuation '
             'are characters like any other; case matters. The empty string encodes to "". Raise ValueError if the '
             'text contains any digit.')
    instruction = _pick(rng, _templates(fn, 'text', file, 'run-length encode a string', rules))

    def ref(text):
        return _rle_reference(text, count_first, keep_ones)

    cases = [_case(ref, [''.join(_pick(rng, _RLE_ALPHABET) for _ in range(rng.randint(3, 14)))]) for _ in range(5)]
    cases += [_case(ref, ['']), _case(ref, ['x']), _case(ref, ['aaaaaaaaaaaa'], long_run=True), _case(ref, ['aAaa']),
              _case(ref, ['ab1'])]
    return {'family': 'run_length', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(text):\n    return None\n', 'cases': cases,
            'params': {'count_first': count_first, 'keep_ones': keep_ones}}


# ---------------------------------------------------------------- R3 grid rotation
def _rotate_reference(grid, turns, clockwise):
    if not grid:
        return []
    if any(len(row) != len(grid[0]) for row in grid):
        raise ValueError('ragged grid')
    out = [list(row) for row in grid]
    if not grid[0]:
        return out
    for _ in range(turns % 4 if clockwise else (-turns) % 4):
        out = [list(row) for row in zip(*out[::-1])]
    return out


def grid_rotate(seed: int) -> dict:
    rng = random.Random(f'grid_rotate:{seed}')
    fn = _pick(rng, ['rotate', 'turn_grid', 'spin_board', 'rotate_tiles'])
    file = _pick(rng, ['grid.py', 'board.py', 'tiles.py'])
    clockwise = rng.random() < 0.5
    way = 'clockwise' if clockwise else 'counter-clockwise'
    rules = (f'The grid is a list of rows (lists) of equal length. Rotate it by 90 degrees {way}, turns times; turns '
             'is any integer, negative turns rotate the other way and only turns modulo 4 matters. Return a new list '
             'of lists and do not modify the input. An empty grid ([]) or a grid of empty rows is returned unchanged '
             'as a new list. Raise ValueError if the rows have different lengths.')
    instruction = _pick(rng, _templates(fn, 'grid, turns', file, f'rotate a grid {way}', rules))

    def ref(grid, turns):
        return _rotate_reference(grid, turns, clockwise)

    def random_grid():
        h, w = rng.randint(1, 4), rng.randint(1, 4)
        return [[rng.randint(0, 9) for _ in range(w)] for _ in range(h)]

    cases = [_case(ref, [random_grid(), rng.randint(-5, 6)]) for _ in range(5)]
    cases += [_case(ref, [[[1, 2, 3], [4, 5, 6]], 1]), _case(ref, [[[1, 2], [3, 4]], -1]), _case(ref, [[], 3]),
              _case(ref, [[[1, 2], [3]], 1]), _case(ref, [[[5, 6]], 4])]
    return {'family': 'grid_rotate', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(grid, turns):\n    return None\n', 'cases': cases,
            'params': {'clockwise': clockwise}}


# ---------------------------------------------------------------- R4 version sorting
def _version_key(text, pad):
    parts = text.split('.')
    if not text or any(not p.isdigit() for p in parts):
        raise ValueError(f'bad version {text!r}')
    nums = [int(p) for p in parts]
    if pad:
        while len(nums) > 1 and nums[-1] == 0:
            nums.pop()
    return nums


def _versions_reference(versions, descending, pad):
    keyed = [(_version_key(v, pad), v) for v in versions]
    return [v for _, v in sorted(keyed, key=lambda kv: (kv[0], kv[1]), reverse=descending)]


def version_sort(seed: int) -> dict:
    rng = random.Random(f'version_sort:{seed}')
    fn = _pick(rng, ['sort_versions', 'order_releases', 'rank_versions', 'sorted_tags'])
    file = _pick(rng, ['versions.py', 'releases.py', 'semver_tools.py'])
    descending = rng.random() < 0.5
    pad = rng.random() < 0.5
    order = 'newest first (descending)' if descending else 'oldest first (ascending)'
    zeros = ('Missing trailing parts count as 0, so "1.2" and "1.2.0" are equal versions.' if pad
             else 'A shorter version that is a prefix of a longer one is older, so "1.2" comes before "1.2.0".')
    rules = (f'Each version is a string of dot-separated non-negative integers like "1.10.2". Compare part by part as '
             f'integers (so "1.10" is newer than "1.9") and return a new list ordered {order}. {zeros} Equal versions '
             f'are ordered by their string, in the same direction. Raise ValueError for an empty string or any '
             'non-numeric part.')
    instruction = _pick(rng, _templates(fn, 'versions', file, 'sort version strings', rules))

    def ref(versions):
        return _versions_reference(versions, descending, pad)

    def random_version():
        return '.'.join(str(rng.randint(0, 12)) for _ in range(rng.randint(1, 4)))

    cases = [_case(ref, [[random_version() for _ in range(rng.randint(2, 6))]]) for _ in range(5)]
    cases += [_case(ref, [['1.9', '1.10', '1.2']]), _case(ref, [['1.2.0', '1.2', '1.1.9']], padding=True),
              _case(ref, [[]]), _case(ref, [['1.a']]), _case(ref, [['2', '']])]
    return {'family': 'version_sort', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(versions):\n    return None\n', 'cases': cases,
            'params': {'descending': descending, 'pad': pad}}


# ---------------------------------------------------------------- R4 round-2 families (new, 2026-11-15)
def _spiral_reference(grid, clockwise):
    if not grid:
        return []
    if any(len(row) != len(grid[0]) for row in grid):
        raise ValueError('ragged grid')
    rows = [list(row) for row in grid]
    if not clockwise:
        rows = [list(col) for col in zip(*rows)]            # counter-clockwise from the top-left = clockwise on the transpose
    out = []
    while rows and rows[0]:
        out += rows.pop(0)
        rows = [list(col) for col in zip(*rows)][::-1]
    return out


def spiral_walk(seed: int) -> dict:
    rng = random.Random(f'spiral_walk:{seed}')
    fn = _pick(rng, ['spiral', 'spiral_order', 'unwind', 'walk_spiral'])
    file = _pick(rng, ['spiral.py', 'matrix_walk.py', 'unwind.py'])
    clockwise = rng.random() < 0.5
    way = ('clockwise: first along the top row to the right, then down the last column' if clockwise
           else 'counter-clockwise: first down the first column, then right along the bottom row')
    rules = (f'The grid is a list of rows (lists) of equal length. Start at the top-left cell and walk inwards in a '
             f'spiral, {way}, and so on until every cell has been visited once. Return the visited values as one flat '
             'list. An empty grid ([]) or a grid of empty rows gives []. Raise ValueError if the rows have different '
             'lengths.')
    instruction = _pick(rng, _templates(fn, 'grid', file, 'list the cells of a grid in spiral order', rules))

    def ref(grid):
        return _spiral_reference(grid, clockwise)

    def random_grid():
        h, w = rng.randint(1, 4), rng.randint(1, 5)
        return [[rng.randint(0, 99) for _ in range(w)] for _ in range(h)]

    cases = [_case(ref, [random_grid()]) for _ in range(5)]
    cases += [_case(ref, [[[1, 2, 3], [4, 5, 6], [7, 8, 9]]]), _case(ref, [[[1, 2, 3, 4]]]), _case(ref, [[[1], [2], [3]]]),
              _case(ref, [[]]), _case(ref, [[[1, 2], [3]]]), _case(ref, [[[1, 2], [3, 4], [5, 6], [7, 8]]])]
    return {'family': 'spiral_walk', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(grid):\n    return None\n', 'cases': cases, 'params': {'clockwise': clockwise}}


def _duration_reference(text, minutes, spaces):
    units = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    parts, rest = [], text
    if not spaces and ' ' in text:
        raise ValueError('spaces are not allowed')
    rest = rest.replace(' ', '')
    while rest:
        digits = ''
        while rest and rest[0].isdigit():
            digits, rest = digits + rest[0], rest[1:]
        if not digits or not rest or rest[0] not in units:
            raise ValueError(f'bad duration {text!r}')
        parts.append((int(digits), rest[0]))
        rest = rest[1:]
    order = [list(units).index(unit) for _, unit in parts]
    if not parts or order != sorted(set(order)):
        raise ValueError(f'bad duration {text!r}')
    seconds = sum(n * units[unit] for n, unit in parts)
    return seconds // 60 if minutes else seconds


def duration_parse(seed: int) -> dict:
    rng = random.Random(f'duration_parse:{seed}')
    fn = _pick(rng, ['parse_duration', 'to_seconds', 'duration_value', 'read_timespan'])
    file = _pick(rng, ['durations.py', 'timespan.py', 'timeparse.py'])
    minutes = rng.random() < 0.5
    spaces = rng.random() < 0.5
    result = 'the total number of whole minutes (leftover seconds are dropped)' if minutes else 'the total number of seconds'
    gap = ('Spaces between the parts are allowed and ignored ("1h 30m").' if spaces
           else 'The text must not contain spaces; raise ValueError if it does.')
    rules = (f'A duration is one or more parts written as a non-negative integer followed by a unit: d (days), h (hours), '
             f'm (minutes), s (seconds), for example "1d2h" or "90m15s". Return {result} as an int. {gap} The units must '
             'appear from largest to smallest and each at most once. Raise ValueError for an empty text, a missing '
             'number, an unknown unit, a repeated unit or units in the wrong order.')
    instruction = _pick(rng, _templates(fn, 'text', file, 'convert a duration text to a number', rules))

    def ref(text):
        return _duration_reference(text, minutes, spaces)

    def random_text():
        units = sorted(rng.sample(range(4), rng.randint(1, 4)))
        return (' ' if spaces and rng.random() < 0.5 else '').join(f"{rng.randint(0, 99)}{'dhms'[u]}" for u in units)

    cases = [_case(ref, [random_text()]) for _ in range(5)]
    cases += [_case(ref, ['1h30m']), _case(ref, ['2d']), _case(ref, ['90m15s']), _case(ref, ['1h 30m'], spacing=True),
              _case(ref, ['']), _case(ref, ['30m1h']), _case(ref, ['1h2h']), _case(ref, ['5x']), _case(ref, ['h'])]
    return {'family': 'duration_parse', 'instruction': instruction, 'file': file, 'function': fn,
            'initial_source': f'def {fn}(text):\n    return None\n', 'cases': cases,
            'params': {'minutes': minutes, 'spaces': spaces}}


CODE_REPLAY_FAMILIES = {'rpn_eval': rpn_eval, 'run_length': run_length, 'grid_rotate': grid_rotate,
                        'version_sort': version_sort}
# R4 (docs/plans/cards/R4.md): the families a second round may learn. grid_rotate gave no replay rows (0/96), version_sort
# gave 63 of the student's own passing rows; spiral_walk and duration_parse have never been run or trained on.
CODE_NEW_FAMILIES = {'spiral_walk': spiral_walk, 'duration_parse': duration_parse}
ROUND2_FAMILIES = ('grid_rotate', 'version_sort', 'spiral_walk', 'duration_parse')

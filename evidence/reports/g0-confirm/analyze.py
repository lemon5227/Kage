"""Pre-registered analysis of the G0 confirmation run (docs/plans/g0-confirm-prereg.md).

  python3 evidence/reports/g0-confirm/analyze.py      # writes analysis.json next to this file

Task = unit; the three runs are averaged within a task; contrasts are paired by task; exact two-sided sign-flip
(the same implementation as docs/paper/v0.5-support/verify.py); p values are nominal. Cells whose run kept failing
in setup (infra errors, after two reruns) count as failures (primary, as pre-registered) and are dropped in a
sensitivity analysis.
"""
from collections import Counter, defaultdict
from fractions import Fraction
from math import lcm
from pathlib import Path
import json
import random

RAW = Path(__file__).resolve().parent / 'raw'
TASKS = json.loads((Path(__file__).resolve().parents[3] / 'eval/desktop_v2_confirm/tasks.json').read_text())['tasks']
GROUPING = sorted(t['task_id'] for t in TASKS if t.get('kind') == 'grouping')
CONTROL = sorted(t['task_id'] for t in TASKS if t.get('kind') == 'precedence_control')
TE = sorted(t['task_id'] for t in TASKS if t['family'] == 'textedit')


def exact_signflip(diffs):
    scale = lcm(*[d.denominator for d in diffs]) if diffs else 1
    ints = [abs(int(d * scale)) for d in diffs]
    observed = abs(sum(int(d * scale) for d in diffs))
    dist = Counter({0: 1})
    for v in ints:
        nxt = Counter()
        for s, c in dist.items():
            nxt[s + v] += c
            nxt[s - v] += c
        dist = nxt
    return Fraction(sum(c for s, c in dist.items() if abs(s) >= observed), 2 ** len(ints))


def boot(diffs, n=10000, seed=20261028):
    rng = random.Random(seed)
    vals = [float(d) for d in diffs]
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3)


def rates(arm, drop_infra=False):
    acc = defaultdict(list)
    for line in (RAW / arm / 'results.jsonl').read_text().splitlines():
        r = json.loads(line)
        if drop_infra and r.get('error'):
            continue
        acc[r['task_id']].append(Fraction(int(bool(r['check'].get('passed')))))
    return {t: sum(v) / len(v) for t, v in acc.items()}


def counts(arm, tasks):
    rows = [json.loads(l) for l in (RAW / arm / 'results.jsonl').read_text().splitlines()]
    rows = [r for r in rows if r['task_id'] in tasks]
    return {'passed': sum(bool(r['check'].get('passed')) for r in rows), 'n': len(rows),
            'infra_failures': sum(bool(r.get('error')) for r in rows)}


def paired(a, b, tasks, drop_infra=False):
    ra, rb = rates(a, drop_infra), rates(b, drop_infra)
    d = [ra[t] - rb[t] for t in tasks]
    p = exact_signflip(d)
    return {'contrast': f'{a} vs {b}', 'tasks': len(tasks), 'mean_diff': round(float(sum(d) / len(d)), 3),
            'improved': sum(x > 0 for x in d), 'worse': sum(x < 0 for x in d), 'tied': sum(x == 0 for x in d),
            'p_fraction': f'{p.numerator}/{p.denominator}', 'p': round(float(p), 4), 'boot95': boot(d),
            'per_task': {t: str(x) for t, x in zip(tasks, d)}}


CALC = ['calc-none', 'calc-system', 'calc-planonly', 'calc-adjacent', 'calc-plan']
PRIMARY = [('calc-plan', 'calc-none'), ('calc-adjacent', 'calc-system'), ('calc-plan', 'calc-planonly'),
           ('calc-plan', 'calc-adjacent')]
out = {'counts': {'grouping': {a: counts(a, GROUPING) for a in CALC},
                  'precedence_control': {a: counts(a, CONTROL) for a in CALC},
                  'textedit': {a: counts(a, TE) for a in ('te-v2', 'te-v4')}},
       'primary': [paired(a, b, GROUPING) for a, b in PRIMARY],
       'secondary_S1': paired('te-v4', 'te-v2', TE),
       'sensitivity_drop_infra': [paired(a, b, GROUPING, drop_infra=True) for a, b in PRIMARY],
       'exploratory_vs_none': [paired(a, 'calc-none', GROUPING) for a in CALC[1:]]}
(Path(__file__).resolve().parent / 'analysis.json').write_text(json.dumps(out, indent=1, ensure_ascii=False))
for k in ('counts',):
    print(json.dumps(out[k], ensure_ascii=False))
for row in out['primary'] + [out['secondary_S1']] + out['sensitivity_drop_infra'] + out['exploratory_vs_none']:
    print(row['contrast'], row['mean_diff'], f"{row['improved']}/{row['worse']}/{row['tied']}", row['p_fraction'], row['boot95'])

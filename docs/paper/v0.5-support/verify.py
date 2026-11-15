"""v0.5 independent check of the disputed numbers (reads only public evidence; no models, no network).

  python3 docs/paper/v0.5-support/verify.py        # writes verify.json next to this file

Task-level analysis: repeats are averaged within a task; contrasts are paired within task; the two-sided sign-flip
probability is computed exactly for every set size by dynamic programming over integer-scaled differences
(no Monte Carlo), and a task-bootstrap interval (fixed seed) is given as a description only.
"""
from collections import Counter, defaultdict
from fractions import Fraction
from math import lcm
from pathlib import Path
import json
import random
import tarfile

ROOT = Path(__file__).resolve().parents[3]
G0 = ROOT / 'evidence/reports/g0'
NEG = {'read_preserve', 'inspect_question', 'lookalike_readonly'}
LEARN = {'subset_selection', 'interval_merge', 'log_aggregation', 'csv_transform'}
HELD = {'text_normalize', 'config_migrate'}


def checkpoints(version, contains, arm):
    with tarfile.open(ROOT / f'evidence/kaggle/v{version}-results.tar.gz') as tar:
        for member in tar.getmembers():
            if member.name.endswith(f'/{arm}/checkpoints.jsonl') and contains in member.name:
                return [json.loads(l) for l in tar.extractfile(member).read().decode().splitlines()]
    raise KeyError((version, contains, arm))


def task_rates(runs, checkpoint='cp0'):
    acc = defaultdict(list)
    for rows in runs:
        for r in rows:
            if r['checkpoint'] == checkpoint:
                acc[r['task_id']].append(Fraction(int(r['score'] >= 1)))
    return {t: sum(v) / len(v) for t, v in acc.items()}


def g0_rates(arm):
    acc = defaultdict(list)
    for line in open(G0 / arm / 'results.jsonl'):
        r = json.loads(line)
        acc[r['task_id']].append(Fraction(int(bool(r['check']['passed']))))
    return {t: sum(v) / len(v) for t, v in acc.items()}


def exact_signflip(diffs):
    """Exact two-sided P(|sum of randomly signed diffs| >= |observed sum|)."""
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
    total = 2 ** len(ints)
    return Fraction(sum(c for s, c in dist.items() if abs(s) >= observed), total)


def boot(diffs, n=10000, seed=20261028):
    rng = random.Random(seed)
    vals = [float(d) for d in diffs]
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3)


def paired(name, a, b, tasks):
    tasks = sorted(tasks)
    d = [a[t] - b[t] for t in tasks]
    p = exact_signflip(d)
    return {'name': name, 'tasks': len(tasks), 'mean_diff': round(float(sum(d) / len(d)), 3),
            'improved': sum(x > 0 for x in d), 'worse': sum(x < 0 for x in d), 'tied': sum(x == 0 for x in d),
            'p_exact': float(p), 'p_fraction': f'{p.numerator}/{p.denominator}', 'boot95': boot(d),
            'per_task': {t: str(a[t] - b[t]) for t in tasks}}


def count(rates, tasks, repeats=3):
    return f'{int(sum(rates[t] for t in tasks) * repeats)}/{len(tasks) * repeats}'


out = {}
# C4 round 1 (v28) and round 2 (v33)
c4 = {arm: task_rates([checkpoints(28, 'e1/c4', f'{arm}-r{i}') for i in (1, 2, 3)]) for arm in ('V1', 'V2', 'V2PK', 'V2PKST')}
prefs = sorted(t for t in c4['V1'] if 'web_prefs' in t)
out['c4_settings_counts'] = {arm: count(c4[arm], prefs) for arm in c4}
out['c4_v1_v2_settings'] = paired('C4 settings V2 vs V1', c4['V2'], c4['V1'], prefs)
out['c4_v2_v2pkst_settings'] = paired('C4 settings V2PKST vs V2', c4['V2PKST'], c4['V2'], prefs)
c4b = {arm: task_rates([checkpoints(33, 'e1/c4b', f'{arm}-r{i}') for i in (1, 2, 3)]) for arm in ('V2PKTSTCK', 'R3EV2PKTSTCK')}
inv = sorted(t for t in c4b['V2PKTSTCK'] if 'web_invoice' in t)
out['c4b_counts'] = {arm: {'all': count(c4b[arm], sorted(c4b[arm])), 'invoice': count(c4b[arm], inv)} for arm in c4b}
out['c4b_r3e_vs_raw_all'] = paired('C4b R3e vs raw (same interface, all 30)', c4b['R3EV2PKTSTCK'], c4b['V2PKTSTCK'], sorted(c4b['V2PKTSTCK']))
out['c4b_r3e_vs_raw_invoice'] = paired('C4b R3e vs raw (invoice)', c4b['R3EV2PKTSTCK'], c4b['V2PKTSTCK'], inv)

# G0: per-family counts and the contrasts
arms = ['a0-baseline-v1', 'a0-test-v2', 'a0-test-v2-lessons', 'a0-test-v2-planonly', 'a0-test-v2-plan',
        'a0-te-v3', 'a0-te-v4', 'a0-final-v4-plan']
g0 = {arm: g0_rates(arm) for arm in arms}
TEST = {'calc_chain2', 'calc_chain3', 'te_fix2', 'te_append2', 'te_write2'}
family = lambda t: 'calculator' if t.startswith('calc') else ('textedit' if t.startswith('te_') else 'settings')
fam_counts = {}
for arm in arms:
    groups = defaultdict(list)
    for t in g0[arm]:
        groups[f"{'test' if t in TEST else 'train'}-{family(t)}"].append(t)
    fam_counts[arm] = {k: count(g0[arm], v) for k, v in sorted(groups.items())}
out['g0_family_counts'] = fam_counts
variants = sorted(TEST)
out['g0_plan_vs_none'] = paired('G0 lessons beside task + plan vs none', g0['a0-test-v2-plan'], g0['a0-test-v2'], variants)
out['g0_planonly_vs_none'] = paired('G0 plan only vs none', g0['a0-test-v2-planonly'], g0['a0-test-v2'], variants)
out['g0_system_vs_none'] = paired('G0 lessons in system prompt vs none', g0['a0-test-v2-lessons'], g0['a0-test-v2'], variants)
out['g0_plan_vs_planonly'] = paired('G0 lessons beside task + plan vs plan only', g0['a0-test-v2-plan'], g0['a0-test-v2-planonly'], variants)
fill = {t: v for t, v in g0['a0-baseline-v1'].items() if t.startswith('te_')}
fill.update({t: v for t, v in g0['a0-test-v2'].items() if t.startswith('te_')})
te = sorted(fill)
out['te_v4_vs_fill'] = paired('TextEdit v4 vs whole-text fill (v1 train + v2 variants)', g0['a0-te-v4'], fill, te)
out['te_v4_vs_v3'] = paired('TextEdit v4 vs v3', g0['a0-te-v4'], g0['a0-te-v3'], te)
out['te_final_vs_v4'] = paired('TextEdit final (v4 + lessons + plan) vs v4 without lessons', g0['a0-final-v4-plan'], g0['a0-te-v4'], te)
train = sorted(t for t in g0['a0-baseline-v1'])
out['g0_train_final_vs_baseline'] = paired('G0 training tasks: final (v4 + lessons + plan) vs baseline v1', g0['a0-final-v4-plan'], g0['a0-baseline-v1'], train)
# the four lessons were written from failures on these training tasks (in-sample for the final 29/30)
out['g0_lessons_source'] = [e['task_id'] for e in json.load(open(G0 / 'a0-baseline-v1' / 'teach-log.json'))['entries']]

# E-1 (raw baseline evaluated once; learning arms = two streams)
a0 = checkpoints(6, 'e1/A0', 'A0')
fam = {r['task_id']: r['family'] for r in a0 if r['checkpoint'] == 'cp0'}
a0r = task_rates([a0])
a3 = task_rates([checkpoints(7, 'e1/seed1', 'A3'), checkpoints(7, 'e1/seed2', 'A3')], 'cp60')
a4 = task_rates([checkpoints(6, 'e1/seed1', 'A4'), checkpoints(6, 'e1/seed2', 'A4')], 'cp60')
in_t = sorted(t for t in a0r if fam[t] in LEARN)
held_t = sorted(t for t in a0r if fam[t] in HELD)
out['e1_A3_vs_A0'] = paired('E-1 memory vs raw (in-family)', a3, a0r, in_t)
out['e1_A4_vs_A0'] = paired('E-1 skills vs raw (in-family)', a4, a0r, in_t)
out['e1_A3_vs_A4'] = paired('E-1 memory vs skills (in-family)', a3, a4, in_t)
out['e1_A3_vs_A0_held'] = paired('E-1 memory vs raw (held-out)', a3, a0r, held_t)

# R3 series (v26 same session; v29-v32 single-run anchors) and negative skill misuse
def r3(version, arm, runs=(1, 2, 3)):
    rows = [checkpoints(version, 'e1/r3' if version == 26 else '/file', f'{arm}-r{i}') for i in runs]
    return task_rates(rows), rows

r3_sets = {'R3': (26, 'L3'), 'R3b': (29, 'r3b'), 'R3c': (30, 'r3c'), 'R3d': (31, 'r3d'), 'R3e': (32, 'r3e')}
base26, base_rows = r3(26, 'A0')
in26 = sorted(t for t in base26 if fam.get(t) in LEARN)
held26 = sorted(t for t in base26 if fam.get(t) in HELD)
neg26 = sorted(t for t in base26 if fam.get(t) in NEG)
summary = {'Base (v26, 3 runs)': {'in': count(base26, in26), 'held': count(base26, held26)}}
misuse = {}
for name, (version, arm) in r3_sets.items():
    rates, rows = r3(version, arm)
    anchor, anchor_rows = r3(version, 'A0', runs=(1,) if version != 26 else (1, 2, 3))
    entry = {'in': count(rates, in26), 'held': count(rates, held26),
             'anchor_in': count(anchor, in26, 1 if version != 26 else 3),
             'anchor_held': count(anchor, held26, 1 if version != 26 else 3)}
    neg_rows = [r for run in rows for r in run if r['checkpoint'] == 'cp0' and r['family'] in NEG]
    bad = [r for r in neg_rows if r.get('misuse')]
    misuse[name] = {'executions': f'{len(bad)}/{len(neg_rows)}', 'tasks': sorted({r['task_id'] for r in bad}),
                    'families': dict(Counter(r['family'] for r in bad)), 'failed_negative': sum(r['score'] < 1 for r in neg_rows)}
    summary[name] = entry
    out[f'{name}_vs_anchor_in'] = paired(f'{name} vs its session anchor (in-family)', rates, anchor, in26)
    out[f'{name}_vs_anchor_held'] = paired(f'{name} vs its session anchor (held-out)', rates, anchor, held26)
base_neg = [r for run in base_rows for r in run if r['checkpoint'] == 'cp0' and r['family'] in NEG]
misuse['Base (v26)'] = {'executions': f"{sum(bool(r.get('misuse')) for r in base_neg)}/{len(base_neg)}"}
web_ad = task_rates([checkpoints(26, 'e1/r3/web', f'L3-r{i}') for i in (1, 2, 3)])
web_base = task_rates([checkpoints(26, 'e1/r3/web', f'A0-r{i}') for i in (1, 2, 3)])
web_learned = sorted(t for t in web_base if any(k in t for k in ('web_invoice', 'web_prefs', 'web_catalog')))
out['r3_web_counts'] = {'base': count(web_base, web_learned), 'R3': count(web_ad, web_learned)}
out['R3_vs_anchor_web'] = paired('R3 vs its session anchor (learned web)', web_ad, web_base, web_learned)
out['r3_summary'] = summary
out['negative_skill_misuse'] = misuse
out['negative_counts'] = {'negative_tasks': len(neg26), 'lookalike_tasks': sum(fam[t] == 'lookalike_readonly' for t in neg26)}

# Second student (Nemotron-3-Nano-4B), same protocol; setup errors are excluded from rates
NEMO = ROOT / 'evidence/reports/g0-nemotron'


def nemo_rates(arm):
    acc = defaultdict(list)
    for line in open(NEMO / arm / 'results.jsonl'):
        r = json.loads(line)
        if r.get('error'):
            continue
        acc[r['task_id']].append(Fraction(int(bool(r['check']['passed']))))
    return {t: sum(v) / len(v) for t, v in acc.items()}


def nemo_counts(arm):
    rows = [json.loads(l) for l in open(NEMO / arm / 'results.jsonl')]
    groups = defaultdict(lambda: [0, 0])
    for r in rows:
        if r.get('error'):
            continue
        k = f"{'test' if r['task_id'] in TEST else 'train'}-{family(r['task_id'])}"
        groups[k][0] += bool(r['check']['passed'])
        groups[k][1] += 1
    return {'total': f"{sum(v[0] for v in groups.values())}/{sum(v[1] for v in groups.values())}",
            'setup_errors': sum(bool(r.get('error')) for r in rows), **{k: f'{a}/{b}' for k, (a, b) in sorted(groups.items())}}


nemo_arms = ['a0-train-v2', 'a0-test-v2', 'a0-test-v2-lessons', 'a0-test-v2-planonly', 'a0-test-v2-plan', 'a0-te-v4',
             'a0-final-v4-plan', 'a0-calc-v5', 'a0-final-v5-plan']
nemo = {arm: nemo_rates(arm) for arm in nemo_arms}
out['nemotron_counts'] = {arm: nemo_counts(arm) for arm in nemo_arms}
nfill = {t: v for t, v in nemo['a0-train-v2'].items() if t.startswith('te_')}
nfill.update({t: v for t, v in nemo['a0-test-v2'].items() if t.startswith('te_')})
out['nemo_te_v4_vs_fill'] = paired('Nemotron TextEdit v4 vs whole-text fill (both v2 sessions)', nemo['a0-te-v4'], nfill, sorted(nfill))
out['nemo_plan_vs_none'] = paired('Nemotron lessons beside task + plan vs none', nemo['a0-test-v2-plan'], nemo['a0-test-v2'], variants)
out['nemo_te_final_vs_v4'] = paired('Nemotron TextEdit final vs v4 without lessons (common tasks)', nemo['a0-final-v4-plan'], nemo['a0-te-v4'],
                                    sorted(set(nemo['a0-te-v4']) & set(nemo['a0-final-v4-plan'])))

json.dump(out, open(Path(__file__).with_name('verify.json'), 'w'), indent=1, ensure_ascii=False)
for k, v in out.items():
    if isinstance(v, dict) and 'p_exact' in v:
        print(f"{v['name'][:62]:62s} n={v['tasks']:2d} d={v['mean_diff']:+.3f} {v['improved']}/{v['worse']}/{v['tied']} p={v['p_fraction']} ({v['p_exact']:.4g}) boot{v['boot95']}")
print(json.dumps({k: out[k] for k in ('c4_settings_counts', 'c4b_counts', 'r3_summary', 'negative_skill_misuse', 'g0_lessons_source', 'nemotron_counts')}, ensure_ascii=False, indent=1))

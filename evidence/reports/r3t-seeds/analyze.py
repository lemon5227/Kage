"""R3 training-seed replication (Kaggle v39-v41): two new seeds of the R3 adapter, same data and hyperparameters, fp16 on T4.

  python3 evidence/reports/r3t-seeds/analyze.py      # writes analysis.json next to this file

Same task-level method as docs/paper/v0.5-support/verify.py: repeats averaged within a task, paired by task, exact
two-sided sign-flip; bootstrap intervals are descriptive; p values nominal. Inputs: evidence/kaggle/v41-results.tar.gz
(seeds 1 and 2, three runs each, one same-session base anchor) and v26 (original R3, seed 0 on A100 bf16, three runs,
three-run same-session base).
"""
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
import json
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
src = (ROOT / 'docs/paper/v0.5-support/verify.py').read_text()
v = {'__file__': str(ROOT / 'docs/paper/v0.5-support/verify.py')}
exec(src[:src.index('out = {}')], v)          # helper functions only (exact_signflip, boot, paired, count, task_rates)
paired, count, task_rates, LEARN, HELD = v['paired'], v['count'], v['task_rates'], v['LEARN'], v['HELD']


def rows(version, prefix, arm):
    with tarfile.open(ROOT / f'evidence/kaggle/v{version}-results.tar.gz') as tar:
        for m in tar.getmembers():
            if m.name.startswith(prefix) and m.name.endswith(f'/{arm}/checkpoints.jsonl'):
                return [json.loads(l) for l in tar.extractfile(m).read().decode().splitlines()]
    raise KeyError((version, prefix, arm))


def arm(version, prefix, name, runs=(1, 2, 3)):
    return [rows(version, prefix, f'{name}-r{i}') for i in runs]


file41 = {s: arm(41, 'e1/ae/file', s) for s in ('r3t1', 'r3t2')} | {'A0': arm(41, 'e1/ae/file', 'A0', (1,))}
web41 = {s: arm(41, 'e1/ae/web', s) for s in ('r3t1', 'r3t2')} | {'A0': arm(41, 'e1/ae/web', 'A0', (1,))}
file26 = {'R3': arm(26, 'e1/r3', 'L3'), 'A0': arm(26, 'e1/r3', 'A0')}
web26 = {'R3': arm(26, 'e1/r3/web', 'L3'), 'A0': arm(26, 'e1/r3/web', 'A0')}
fam = {r['task_id']: r['family'] for run in file26['A0'] for r in run if r['checkpoint'] == 'cp0'}
in_f = sorted(t for t in fam if fam[t] in LEARN)
held = sorted(t for t in fam if fam[t] in HELD)
rate = {k: task_rates(x) for k, x in {**{f'{a}@41': r for a, r in file41.items()}, **{f'{a}@26': r for a, r in file26.items()}}.items()}
wrate = {k: task_rates(x) for k, x in {**{f'{a}@41': r for a, r in web41.items()}, **{f'{a}@26': r for a, r in web26.items()}}.items()}
web_learned = sorted(t for t in wrate['A0@26'] if any(k in t for k in ('web_invoice', 'web_prefs', 'web_catalog')))
reps = {'r3t1@41': 3, 'r3t2@41': 3, 'A0@41': 1, 'R3@26': 3, 'A0@26': 3}


def per_run(runs, tasks):
    return [sum(r['score'] >= 1 for r in run if r['checkpoint'] == 'cp0' and r['task_id'] in tasks) for run in runs]


out = {'counts': {}, 'per_run': {}, 'contrasts': {}}
for k in reps:
    out['counts'][k] = {'in_family': count(rate[k], in_f, reps[k]), 'held_out': count(rate[k], held, reps[k]),
                        'learned_web': count(wrate[k], web_learned, reps[k])}
for k, runs in [('r3t1@41', file41['r3t1']), ('r3t2@41', file41['r3t2']), ('A0@41', file41['A0']), ('R3@26', file26['R3']), ('A0@26', file26['A0'])]:
    out['per_run'][k] = {'in_family': per_run(runs, set(in_f)), 'held_out': per_run(runs, set(held))}
neg = [r for s in ('r3t1', 'r3t2') for run in file41[s] for r in run if r['checkpoint'] == 'cp0' and r['family'] in v['NEG']]
out['negative_misuse'] = {'executions': f"{sum(bool(r.get('misuse')) for r in neg)}/{len(neg)}",
                          'tasks': sorted({r['task_id'] for r in neg if r.get('misuse')})}
pooled = {t: (rate['r3t1@41'][t] + rate['r3t2@41'][t]) / 2 for t in in_f + held}
C = out['contrasts']
for s in ('r3t1', 'r3t2'):
    C[f'{s}_vs_anchor41_in'] = paired(f'{s} vs same-session base (v41, 1 run), in-family', rate[f'{s}@41'], rate['A0@41'], in_f)
    C[f'{s}_vs_anchor41_held'] = paired(f'{s} vs same-session base (v41, 1 run), held-out', rate[f'{s}@41'], rate['A0@41'], held)
    C[f'{s}_vs_base26_in'] = paired(f'{s} vs v26 base (3 runs, other session), in-family', rate[f'{s}@41'], rate['A0@26'], in_f)
    C[f'{s}_vs_base26_held'] = paired(f'{s} vs v26 base (3 runs, other session), held-out', rate[f'{s}@41'], rate['A0@26'], held)
    C[f'{s}_vs_R3_in'] = paired(f'{s} vs original R3 seed 0 (v26), in-family', rate[f'{s}@41'], rate['R3@26'], in_f)
    C[f'{s}_vs_R3_held'] = paired(f'{s} vs original R3 seed 0 (v26), held-out', rate[f'{s}@41'], rate['R3@26'], held)
    C[f'{s}_vs_anchor41_web'] = paired(f'{s} vs same-session base, learned web', wrate[f'{s}@41'], wrate['A0@41'], web_learned)
C['seeds12_vs_base26_in'] = paired('mean of seeds 1-2 vs v26 base, in-family', pooled, rate['A0@26'], in_f)
C['seeds12_vs_base26_held'] = paired('mean of seeds 1-2 vs v26 base, held-out', pooled, rate['A0@26'], held)
C['anchor41_vs_base26_in'] = paired('v41 base (1 run) vs v26 base (3 runs), in-family: session drift', rate['A0@41'], rate['A0@26'], in_f)
C['anchor41_vs_base26_held'] = paired('v41 base vs v26 base, held-out: session drift', rate['A0@41'], rate['A0@26'], held)
for c in C.values():
    c.pop('per_task')
with tarfile.open(ROOT / 'evidence/kaggle/v41-results.tar.gz') as tar:
    summary = json.load(tar.extractfile('e1/ae/summary.json'))
out['general'] = {k: f"{g['passed']}/{g['total']}" for k, g in summary['general'].items()}
(HERE / 'analysis.json').write_text(json.dumps(out, indent=1))
json.dump({k: out[k] for k in ('counts', 'per_run', 'negative_misuse', 'general')}, sys.stdout, indent=1)
for k, c in C.items():
    print(f"\n{k}: {c['mean_diff']:+.2f}  {c['improved']}/{c['worse']}/{c['tied']}  p={c['p_fraction']}  boot={c['boot95']}")

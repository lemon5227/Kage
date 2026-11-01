"""R3g (keep the read-back check) evaluated against R3 and the base student (Kaggle v44; plan docs/plans/r3f-forgetting-fix.md).

  python3 evidence/reports/r3g/analyze.py      # writes analysis.json next to this file

R3g is R3's data and hyperparameters with one change: every trajectory that ends with a final write_file gets an exact
read_file of that path before its final answer (scripts/experiments/r3_data.py --readback, +273 rows). Two seeds
(r3g0, r3g1), three runs each, one same-session base anchor (A0). Comparisons: the same-session anchor, the R3 seeds
1-2 adapters (v41, same T4 fp16 recipe without read-back) and the v26 base (three runs). Statistics are the task-level
method of docs/paper/v0.5-support/verify.py (exact two-sided sign-flip, nominal p).

Read-back rate: among cp0 tasks where the model wrote a file, the share where it later called read_file on a path it
had written. Read from the model traces (the last request of each task holds the whole conversation).
"""
from collections import defaultdict
from pathlib import Path
import json
import re
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
src = (ROOT / 'docs/paper/v0.5-support/verify.py').read_text()
v = {'__file__': str(ROOT / 'docs/paper/v0.5-support/verify.py')}
exec(src[:src.index('out = {}')], v)          # helper functions only
paired, count, task_rates, LEARN, HELD, NEG = v['paired'], v['count'], v['task_rates'], v['LEARN'], v['HELD'], v['NEG']
WEB_LEARN = {'web_invoice', 'web_prefs', 'web_catalog'}
SEEDS = ('r3g0', 'r3g1')


def members(version):
    return tarfile.open(ROOT / f'evidence/kaggle/v{version}-results.tar.gz')


def rows(version, prefix, arm):
    with members(version) as tar:
        for m in tar.getmembers():
            if m.name.startswith(prefix) and m.name.endswith(f'/{arm}/checkpoints.jsonl'):
                return [json.loads(l) for l in tar.extractfile(m).read().decode().splitlines()]
    raise KeyError((version, prefix, arm))


def arm(version, prefix, name, runs=(1, 2, 3)):
    return [rows(version, prefix, f'{name}-r{i}') for i in runs]


def tool_calls(lines):
    last = json.loads(lines[-1])
    for message in last['messages'] + [last.get('response') or {}]:
        for call in (message.get('tool_calls') or []) if isinstance(message, dict) else []:
            fn = call.get('function', call)
            args = fn.get('arguments')
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            yield fn.get('name'), (args or {}).get('path')


def read_back(calls):
    written = set()
    for name, path in calls:
        if name == 'write_file':
            written.add(path)
        elif name == 'read_file' and path in written:
            return True
    return False


def readback_rates(version, prefix):
    """{arm-run: {group: [read back, wrote]}} over cp0 file tasks."""
    out = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    with members(version) as tar:
        for m in tar.getmembers():
            if not (m.isfile() and m.name.startswith(prefix + '/') and '/model-traces/cp0-' in m.name):
                continue
            run = m.name[len(prefix) + 1:].split('/')[0]
            family = re.sub(r'^cp0-stream-v1-|-\d+\.jsonl$', '', m.name.rsplit('/', 1)[1])
            lines = tar.extractfile(m).read().decode().splitlines()
            calls = list(tool_calls(lines)) if lines else []
            if not any(name == 'write_file' for name, _ in calls):
                continue
            group = 'learned' if family in LEARN else 'held_out' if family in HELD else 'other'
            for g in (group, 'all'):
                out[run][g][0] += read_back(calls)
                out[run][g][1] += 1
    return {run: {g: f'{a}/{b}' for g, (a, b) in groups.items()} for run, groups in sorted(out.items())}


def held_out_repair(version, prefix):
    """{arm: counts} over cp0 held-out file tasks: does a read-back lead to a rewrite, and does the rewrite pass?"""
    out = defaultdict(lambda: defaultdict(int))
    with members(version) as tar:
        names = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(prefix + '/')]
        passed = {}
        for m in names:
            if m.name.endswith('/checkpoints.jsonl'):
                run = m.name[len(prefix) + 1:].split('/')[0]
                for line in tar.extractfile(m).read().decode().splitlines():
                    r = json.loads(line)
                    if r['checkpoint'] == 'cp0':
                        passed[run, r['task_id']] = float(r['score']) >= 1
        for m in names:
            family = re.sub(r'^cp0-stream-v1-|-\d+\.jsonl$', '', m.name.rsplit('/', 1)[1])
            if '/model-traces/cp0-' not in m.name or family not in HELD:
                continue
            run = m.name[len(prefix) + 1:].split('/')[0]
            ok = passed.get((run, m.name.rsplit('/', 1)[1][4:-6]), False)
            lines = tar.extractfile(m).read().decode().splitlines()
            written, read, rewrite = set(), False, False
            for name, path in (tool_calls(lines) if lines else []):
                if name == 'write_file':
                    rewrite |= read
                    written.add(path)
                elif name == 'read_file' and path in written:
                    read = True
            c = out[run.rsplit('-r', 1)[0]]
            c['tasks'] += 1
            c['passed'] += ok
            c['read_back'] += read
            c['rewrite_after_read_back'] += rewrite
            c['passed_after_rewrite'] += rewrite and ok
    return {a: dict(c) for a, c in sorted(out.items())}


file44 = {s: arm(44, 'e1/ae/file', s) for s in SEEDS} | {'A0': arm(44, 'e1/ae/file', 'A0', (1,))}
web44 = {s: arm(44, 'e1/ae/web', s) for s in SEEDS} | {'A0': arm(44, 'e1/ae/web', 'A0', (1,))}
file41 = {s: arm(41, 'e1/ae/file', s) for s in ('r3t1', 'r3t2')}
file26 = {'A0': arm(26, 'e1/r3', 'A0')}
fam = {r['task_id']: r['family'] for run in file26['A0'] for r in run if r['checkpoint'] == 'cp0'}
in_f = sorted(t for t in fam if fam[t] in LEARN)
held = sorted(t for t in fam if fam[t] in HELD)
rate = {f'{k}@44': task_rates(x) for k, x in file44.items()} | {f'{k}@41': task_rates(x) for k, x in file41.items()} \
    | {'A0@26': task_rates(file26['A0'])}
wrate = {f'{k}@44': task_rates(x) for k, x in web44.items()}
web_learned = sorted(t for t in wrate['A0@44'] if any(f in t for f in WEB_LEARN))
reps = {'r3g0@44': 3, 'r3g1@44': 3, 'A0@44': 1, 'r3t1@41': 3, 'r3t2@41': 3, 'A0@26': 3}

out = {'counts': {}, 'readback': {}, 'contrasts': {}}
for k, n in reps.items():
    out['counts'][k] = {'in_family': count(rate[k], in_f, n), 'held_out': count(rate[k], held, n)}
    if k in wrate:
        out['counts'][k]['learned_web'] = count(wrate[k], web_learned, n)
out['readback']['v44'] = readback_rates(44, 'e1/ae/file')
out['readback']['v41'] = readback_rates(41, 'e1/ae/file')
out['held_out_repair'] = {'v44': held_out_repair(44, 'e1/ae/file'), 'v41': held_out_repair(41, 'e1/ae/file')}
neg = [r for s in SEEDS for run in file44[s] for r in run if r['checkpoint'] == 'cp0' and r['family'] in NEG]
out['negative_misuse'] = {'executions': f"{sum(bool(r.get('misuse')) for r in neg)}/{len(neg)}",
                          'tasks': sorted({r['task_id'] for r in neg if r.get('misuse')})}
C = out['contrasts']
for s in SEEDS:
    for label, tasks in (('in', in_f), ('held', held)):
        C[f'{s}_vs_anchor44_{label}'] = paired(f'{s} vs same-session base (1 run), {label}', rate[f'{s}@44'],
                                               rate['A0@44'], tasks)
        C[f'{s}_vs_base26_{label}'] = paired(f'{s} vs v26 base (3 runs), {label}', rate[f'{s}@44'], rate['A0@26'], tasks)
    C[f'{s}_vs_anchor44_web'] = paired(f'{s} vs same-session base, learned web', wrate[f'{s}@44'], wrate['A0@44'],
                                       web_learned)
pooled_g = {t: (rate['r3g0@44'][t] + rate['r3g1@44'][t]) / 2 for t in in_f + held}
pooled_t = {t: (rate['r3t1@41'][t] + rate['r3t2@41'][t]) / 2 for t in in_f + held}
C['r3g_vs_r3t_in'] = paired('mean of R3g seeds vs mean of R3 seeds 1-2 (v41), in-family', pooled_g, pooled_t, in_f)
C['r3g_vs_r3t_held'] = paired('mean of R3g seeds vs mean of R3 seeds 1-2 (v41), held-out', pooled_g, pooled_t, held)
for c in C.values():
    c.pop('per_task')
with members(44) as tar:
    summary = json.load(tar.extractfile('e1/ae/summary.json'))
out['general'] = {k: f"{g['passed']}/{g['total']}" for k, g in summary['general'].items()}
(HERE / 'analysis.json').write_text(json.dumps(out, indent=1))
json.dump({k: out[k] for k in ('counts', 'held_out_repair', 'negative_misuse', 'general')}, sys.stdout, indent=1)
for k, c in C.items():
    print(f"\n{k}: {c['mean_diff']:+.2f}  {c['improved']}/{c['worse']}/{c['tied']}  p={c['p_fraction']}  boot={c['boot95']}")

"""R3h deployment gating, evaluated offline from existing runs (no training, no model calls).

  python3 evidence/reports/r3h/analyze.py      # writes analysis.json next to this file

The gate is Kage's own relevance rule (core/evolution/relevance.py): TF-IDF cosine of the visible task instruction
against the instructions the adapter was trained on, adapter on iff the best score >= RELEVANCE_MIN (0.3). The router
sees only instruction text, never the family label or the browser observation.

Why offline is exact: the frozen evals run every task in its own workspace with no memory, skills or learning between
tasks (eval-only cp0), so a gated run is, task by task, the adapter's run where the gate says adapter and the base run
where it says base. We compose those from same-session runs that already exist:
  v26  R3 seed 0 (A100 bf16): adapter 3 runs, base 3 runs
  v32  R3e: adapter 3 runs, base 1 run
  v41  R3 seeds 1, 2 (T4 fp16): adapter 3 runs each, base 1 run
Statistics are the task-level method of docs/paper/v0.5-support/verify.py (exact two-sided sign-flip, nominal p).
"""
from copy import deepcopy
from pathlib import Path
import gzip
import json
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.relevance import RELEVANCE_MIN, InstructionSpace  # noqa: E402

src = (ROOT / 'docs/paper/v0.5-support/verify.py').read_text()
v = {'__file__': str(ROOT / 'docs/paper/v0.5-support/verify.py')}
exec(src[:src.index('out = {}')], v)
paired, count, task_rates, LEARN, HELD, NEG = v['paired'], v['count'], v['task_rates'], v['LEARN'], v['HELD'], v['NEG']
WEB_LEARN = {'web_invoice', 'web_prefs', 'web_catalog'}
CUTS = ('\nFirst use a matching skill_call', '\nInitial browser observation')


def instruction(text):
    for cut in CUTS:
        text = text.split(cut)[0]
    return text.strip()


train = {}
for line in gzip.open(ROOT / 'evidence/reports/r2/sft-v21.jsonl.gz', 'rt'):
    r = json.loads(line)
    train.setdefault(r['task_id'], instruction(r['messages'][1]['content']))
base_space = InstructionSpace()
for text in train.values():
    base_space.observe(text)

evals = {}
for kind, path in (('file', 'eval/stream_v1/eval.json'), ('web', 'eval/stream_web_v1/eval.json')):
    for t in json.loads((ROOT / path).read_text())['tasks']:
        evals[t['task_id']] = {'kind': kind, 'family': t['family'], 'instruction': t['instruction']}


def best(text):
    space = deepcopy(base_space)
    space.observe(text)                    # the agent observes a task before scoring it (TaskClusters.assign)
    return max(space.similarity(text, other) for other in train.values())


score = {t: best(e['instruction']) for t, e in evals.items()}


def group(family):
    return ('learned' if family in LEARN | WEB_LEARN else 'held_out' if family in HELD | {'web_form'}
            else 'negative' if family in NEG else 'other')


def routing(threshold):
    on = {t for t, s in score.items() if s >= threshold}
    table = {}
    for t, e in evals.items():
        row = table.setdefault(f"{e['kind']}:{group(e['family'])}", {'tasks': 0, 'adapter': 0})
        row['tasks'] += 1
        row['adapter'] += t in on
    return on, table


def rows(version, prefix, arm):
    with tarfile.open(ROOT / f'evidence/kaggle/v{version}-results.tar.gz') as tar:
        for m in tar.getmembers():
            if m.name.startswith(prefix) and m.name.endswith(f'/{arm}/checkpoints.jsonl'):
                return [json.loads(l) for l in tar.extractfile(m).read().decode().splitlines()]
    raise KeyError((version, prefix, arm))


SOURCES = {   # name: (version, file prefix, web prefix, adapter arm, adapter runs, base runs)
    'R3 seed 0 (v26)': (26, 'e1/r3/file', 'e1/r3/web', 'L3', 3, 3),
    'R3e (v32)': (32, 'e1/ae/file', 'e1/ae/web', 'r3e', 3, 1),
    'R3 seed 1 (v41)': (41, 'e1/ae/file', 'e1/ae/web', 'r3t1', 3, 1),
    'R3 seed 2 (v41)': (41, 'e1/ae/file', 'e1/ae/web', 'r3t2', 3, 1),
}


def misuse(runs, tasks):
    hits = [r for run in runs for r in run if r['checkpoint'] == 'cp0' and r['task_id'] in tasks]
    return f"{sum(bool(r.get('misuse')) for r in hits)}/{len(hits)}"


on, _ = routing(RELEVANCE_MIN)
fam = {t: e['family'] for t, e in evals.items()}
sets = {'in_family': sorted(t for t in fam if fam[t] in LEARN), 'held_out': sorted(t for t in fam if fam[t] in HELD),
        'negative': sorted(t for t in fam if fam[t] in NEG), 'learned_web': sorted(t for t in fam if fam[t] in WEB_LEARN),
        'web_other': sorted(t for t in fam if evals[t]['kind'] == 'web' and fam[t] not in WEB_LEARN)}

out = {'router': {'rule': f'TF-IDF cosine vs {len(train)} training instructions, adapter iff best >= {RELEVANCE_MIN}',
                  'per_group': routing(RELEVANCE_MIN)[1],
                  'score_range': {g: [round(min(score[t] for t in ts), 3), round(max(score[t] for t in ts), 3)]
                                  for g, ts in sets.items()},
                  'threshold_sweep': {str(th): routing(th)[1] for th in (0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6)}},
       'sources': {}}
for name, (ver, fpre, wpre, arm, na, nb) in SOURCES.items():
    fa = [rows(ver, fpre, f'{arm}-r{i}') for i in range(1, na + 1)]
    fb = [rows(ver, fpre, f'A0-r{i}') for i in range(1, nb + 1)]
    wa = [rows(ver, wpre, f'{arm}-r{i}') for i in range(1, na + 1)]
    wb = [rows(ver, wpre, f'A0-r{i}') for i in range(1, nb + 1)]
    ra, rb = task_rates(fa) | task_rates(wa), task_rates(fb) | task_rates(wb)
    gated = {t: ra[t] if t in on else rb[t] for t in ra}
    res = {'runs': {'adapter': na, 'base': nb}, 'counts': {}, 'contrasts': {}}
    for label, rate, reps in (('base', rb, nb), ('adapter', ra, na), ('gated', gated, na)):
        res['counts'][label] = {s: count(rate, ts, reps) for s, ts in sets.items() if s != 'negative'}
    neg_on = [t for t in sets['negative'] if t in on]
    res['counts']['gated']['negative_misuse'] = (f"{misuse(fa, set(neg_on))} on adapter-routed negatives, "
                                                 f"{misuse(fb, set(sets['negative']) - set(neg_on))} on base-routed")
    res['counts']['adapter']['negative_misuse'] = misuse(fa, set(sets['negative']))
    res['counts']['base']['negative_misuse'] = misuse(fb, set(sets['negative']))
    for s in ('in_family', 'held_out', 'learned_web'):
        res['contrasts'][f'gated_vs_base_{s}'] = paired(f'{name} gated vs base, {s}', gated, rb, sets[s])
        res['contrasts'][f'gated_vs_adapter_{s}'] = paired(f'{name} gated vs adapter, {s}', gated, ra, sets[s])
    for c in res['contrasts'].values():
        c.pop('per_task')
    out['sources'][name] = res

(HERE / 'analysis.json').write_text(json.dumps(out, indent=1))
print(json.dumps(out['router']['per_group'], indent=1))
print('score range', out['router']['score_range'])
for th, tab in out['router']['threshold_sweep'].items():
    print(th, {g: f"{r['adapter']}/{r['tasks']}" for g, r in tab.items()})
for name, res in out['sources'].items():
    print(f'\n== {name}')
    for label, c in res['counts'].items():
        print(f'  {label:8s}', c)
    for k, c in res['contrasts'].items():
        print(f"  {k}: {c['mean_diff']:+.2f} {c['improved']}/{c['worse']}/{c['tied']} p={c['p_fraction']}")

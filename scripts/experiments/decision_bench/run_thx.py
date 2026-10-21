"""Run THX-01 locally on the benchmark; score accuracy, Brier, ECE, latency per task."""
import json, sys, time, collections
import thx01

items = [json.loads(l) for l in open(sys.argv[1])]
agent = thx01.load('doofz/THX-01')
res = []
for it in items:
    t = time.time()
    r = agent.decide(it['state'], it['questions'])
    dt = time.time() - t
    a = r['answers']['q']; gold = it['gold']['q']
    if a['type'] == 'noul':
        p = a['noul']; pred = p >= 0.5; ok = pred == gold; pc = p if gold else 1 - p
    else:
        pred = a['choice']; golds = gold if isinstance(gold, list) else [gold]
        ok = pred in golds; pc = sum(a['probabilities'].get(g, 0) for g in golds)
    conf = max(a['probabilities'].values()) if a['type'] == 'choice' else max(a['noul'], 1 - a['noul'])
    res.append({'task': it['task'], 'id': it['id'], 'pred': pred, 'gold': gold, 'ok': ok,
                'p_gold': pc, 'conf': conf, 'latency_s': dt})
json.dump(res, open(sys.argv[2], 'w'), indent=0, default=str)

by = collections.defaultdict(list)
for r in res:
    by[r['task']].append(r)
def ece(rs, bins=10):
    tot = 0
    for b in range(bins):
        g = [r for r in rs if b / bins <= r['conf'] < (b + 1) / bins or (b == bins - 1 and r['conf'] == 1)]
        if g:
            tot += len(g) * abs(sum(r['ok'] for r in g) / len(g) - sum(r['conf'] for r in g) / len(g))
    return tot / len(rs)
for task, rs in sorted(by.items()):
    acc = sum(r['ok'] for r in rs) / len(rs)
    hi = [r for r in rs if r['conf'] >= 0.9]
    lat = sorted(r['latency_s'] for r in rs)[len(rs) // 2]
    print(f'{task:22s} n={len(rs):3d} acc={acc:.2f} brier={sum((1-r["p_gold"])**2 for r in rs)/len(rs):.3f} '
          f'ece={ece(rs):.3f} conf>=0.9: n={len(hi)} acc={(sum(r["ok"] for r in hi)/len(hi)) if hi else float("nan"):.2f} '
          f'median_latency={lat*1000:.0f}ms')

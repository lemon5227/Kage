"""Run Cloudflare Clef on the same decision benchmark as THX-01 (bench.jsonl / t6.jsonl).

Credentials: ~/.config/kage/teachers/cloudflare.json {account_id, api_token} (never printed or logged).
Every call is charged to the global teacher ledger at Clef's list price ($0.24 / M input tokens, output free),
whether or not the account's free allocation covered it.

  python run_clef.py BENCH.jsonl OUT.json [--limit N] [--model clef|clef-flash]
"""
import argparse, collections, json, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core.evolution.teacher_budget import charge_external, global_teacher_budget, remaining_usd

USD_PER_M_INPUT = 0.24
CRED = Path('~/.config/kage/teachers/cloudflare.json').expanduser()


def to_clef(questions: dict) -> dict:
    out = {}
    for qid, q in questions.items():
        item = {'type': q['type'], 'instructions': q['question']}
        if q['type'] == 'choice':
            item['criteria'] = q['criteria']
        out[qid] = item
    return out


def call(cred: dict, model: str, state: str, questions: dict) -> dict:
    url = f"https://api.cloudflare.com/client/v4/accounts/{cred['account_id']}/ai/run/@cf/cloudflare/{model}"
    body = json.dumps({'model': model, 'state': state, 'questions': to_clef(questions)}).encode()
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Authorization': f"Bearer {cred['api_token']}", 'Content-Type': 'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode(errors='replace')
            if exc.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt * 3)
                continue
            raise SystemExit(f'HTTP {exc.code}: {detail}')
    raise SystemExit('retries exhausted')


def answer_of(a: dict, qtype: str):
    """Normalise an answer to (prediction, probabilities) whatever the exact field names are."""
    if qtype == 'noul':
        p = a.get('noul', a.get('probability', a.get('yes')))
        return p >= 0.5, {'yes': p, 'no': 1 - p}
    probs = a.get('probabilities') or a.get('probs') or {}
    pred = a.get('choice') or a.get('answer') or (max(probs, key=probs.get) if probs else None)
    return pred, probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bench'); ap.add_argument('out')
    ap.add_argument('--limit', type=int); ap.add_argument('--model', default='clef')
    args = ap.parse_args()
    cred = json.loads(CRED.read_text())
    budget = global_teacher_budget()
    items = [json.loads(line) for line in open(args.bench)]
    if args.limit:
        step = max(1, len(items) // args.limit)
        items = items[::step][:args.limit]
    print(f'ledger remaining ${remaining_usd(budget):.4f}; {len(items)} items', flush=True)
    res, tokens_in = [], 0
    for i, it in enumerate(items):
        t = time.time()
        r = call(cred, args.model, it['state'], it['questions'])
        dt = time.time() - t
        result = r.get('result', r)
        usage = result.get('usage', {})
        n_in = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
        tokens_in += n_in
        charge_external(budget, n_in * USD_PER_M_INPUT / 1e6, run_id='decision-clef', call_type='clef')
        if i == 0:
            print('first response keys:', sorted(result), 'answer:', json.dumps(result['answers']['q'])[:300],
                  'usage:', usage, flush=True)
        q = it['questions']['q']
        pred, probs = answer_of(result['answers']['q'], q['type'])
        gold = it['gold']['q']
        golds = gold if isinstance(gold, list) else [gold]
        if q['type'] == 'noul':
            ok = pred == gold; p_gold = probs['yes'] if gold else probs['no']; conf = max(probs.values())
        else:
            ok = pred in golds; p_gold = sum(probs.get(g, 0) for g in golds); conf = max(probs.values()) if probs else 0
        res.append({'task': it['task'], 'id': it['id'], 'pred': pred, 'gold': gold, 'ok': ok,
                    'p_gold': p_gold, 'conf': conf, 'latency_s': dt, 'input_tokens': n_in})
    json.dump(res, open(args.out, 'w'), indent=0, default=str)
    by = collections.defaultdict(list)
    for r in res:
        by[r['task']].append(r)
    for task, rs in sorted(by.items()):
        acc = sum(r['ok'] for r in rs) / len(rs)
        hi = [r for r in rs if r['conf'] >= 0.9]
        lat = sorted(r['latency_s'] for r in rs)[len(rs) // 2]
        print(f"{task:22s} n={len(rs):3d} acc={acc:.2f} brier={sum((1 - r['p_gold']) ** 2 for r in rs) / len(rs):.3f} "
              f"conf>=0.9: n={len(hi)} acc={(sum(r['ok'] for r in hi) / len(hi)) if hi else float('nan'):.2f} "
              f"median_latency={lat * 1000:.0f}ms")
    print(f'input tokens {tokens_in}, charged ${tokens_in * USD_PER_M_INPUT / 1e6:.4f}; '
          f'ledger remaining ${remaining_usd(budget):.4f}')


if __name__ == '__main__':
    main()

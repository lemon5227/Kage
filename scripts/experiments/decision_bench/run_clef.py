"""Run a hosted decision model (Cloudflare Clef, or TypeSafe Jev via OpenCode) on the decision benchmark
(bench.jsonl / t6.jsonl). Both take {model, state, questions} with noul/choice/score questions.

Credentials (never printed or logged): ~/.config/kage/teachers/cloudflare.json {account_id, api_token};
~/.config/kage/teachers/opencode.json {api_key}. Every call is charged to the global teacher ledger at the
model's list input price (output is free for both), whether or not a free allocation covered it.

  python run_clef.py BENCH.jsonl OUT.json [--limit N] [--model clef|clef-flash|jev-1.13-free|jev-1.13]
"""
import argparse, collections, json, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core.evolution.teacher_budget import charge_external, global_teacher_budget, remaining_usd

USD_PER_M_INPUT = {'clef': 0.24, 'clef-flash': 0.24, 'jev-1.13': 0.042, 'jev-1.13-free': 0.042}
TEACHERS = Path('~/.config/kage/teachers').expanduser()


def to_clef(questions: dict) -> dict:
    out = {}
    for qid, q in questions.items():
        item = {'type': q['type'], 'instructions': q['question']}
        if q['type'] == 'choice':
            item['criteria'] = q['criteria']
        out[qid] = item
    return out


def endpoint(model: str) -> tuple[str, str]:
    """(url, bearer token) for a model; the token is only ever placed in the request header."""
    if model.startswith('jev'):
        cred = json.loads((TEACHERS / 'opencode.json').read_text())
        return 'https://opencode.ai/inference/systemone/v1/systemone', cred['api_key']
    cred = json.loads((TEACHERS / 'cloudflare.json').read_text())
    return (f"https://api.cloudflare.com/client/v4/accounts/{cred['account_id']}/ai/run/@cf/cloudflare/{model}",
            cred['api_token'])


class FreeLimit(Exception):
    """The provider's free allocation is used up: stop and keep what is done (never retry into a bill)."""


def call(model: str, state: str, questions: dict) -> dict:
    url, token = endpoint(model)
    body = json.dumps({'model': model, 'state': state, 'questions': to_clef(questions)}).encode()
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
        'User-Agent': 'kage-decision-bench/1'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode(errors='replace')
            if exc.code == 429 and 'FreeUsageLimit' in detail:
                raise FreeLimit(detail)
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
    ap.add_argument('--sleep', type=float, default=0.0, help='seconds between calls (free-tier rate limits)')
    args = ap.parse_args()
    budget = global_teacher_budget()
    items = [json.loads(line) for line in open(args.bench)]
    if args.limit:
        step = max(1, len(items) // args.limit)
        items = items[::step][:args.limit]
    # Every answer is appended to OUT.partial.jsonl at once, so a stopped run resumes where it ended.
    partial = Path(args.out + '.partial.jsonl')
    done = {}
    if partial.exists():
        for line in partial.read_text().splitlines():
            row = json.loads(line)
            done[row['id']] = row
    print(f'ledger remaining ${remaining_usd(budget):.4f}; {len(items)} items, {len(done)} already done', flush=True)
    tokens_in, stopped = 0, None
    for it in items:
        if it['id'] in done:
            continue
        t = time.time()
        try:
            r = call(args.model, it['state'], it['questions'])
        except FreeLimit as exc:
            stopped = str(exc)[:200]
            break
        dt = time.time() - t
        result = r.get('result', r)
        usage = result.get('usage', {})
        n_in = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
        tokens_in += n_in
        charge_external(budget, n_in * USD_PER_M_INPUT[args.model] / 1e6, run_id=f'decision-{args.model}',
                        call_type='decision')
        q = it['questions']['q']
        pred, probs = answer_of(result['answers']['q'], q['type'])
        gold = it['gold']['q']
        golds = gold if isinstance(gold, list) else [gold]
        if q['type'] == 'noul':
            ok = pred == gold; p_gold = probs['yes'] if gold else probs['no']; conf = max(probs.values())
        else:
            ok = pred in golds; p_gold = sum(probs.get(g, 0) for g in golds); conf = max(probs.values()) if probs else 0
        row = {'task': it['task'], 'id': it['id'], 'pred': pred, 'gold': gold, 'ok': ok,
               'p_gold': p_gold, 'conf': conf, 'latency_s': dt, 'input_tokens': n_in}
        done[it['id']] = row
        with partial.open('a') as f:
            f.write(json.dumps(row, default=str) + '\n')
        if args.sleep:
            time.sleep(args.sleep)
    res = [done[it['id']] for it in items if it['id'] in done]
    if stopped:
        print(f'STOPPED (free allocation used up) after {len(res)}/{len(items)}: {stopped}', flush=True)
    else:
        json.dump(res, open(args.out, 'w'), indent=0, default=str)
    by = collections.defaultdict(list)
    for r in res:
        by[r['task']].append(r)
    for task, rs in sorted(by.items()):  # partial if stopped
        acc = sum(r['ok'] for r in rs) / len(rs)
        hi = [r for r in rs if r['conf'] >= 0.9]
        lat = sorted(r['latency_s'] for r in rs)[len(rs) // 2]
        print(f"{task:22s} n={len(rs):3d} acc={acc:.2f} brier={sum((1 - r['p_gold']) ** 2 for r in rs) / len(rs):.3f} "
              f"conf>=0.9: n={len(hi)} acc={(sum(r['ok'] for r in hi) / len(hi)) if hi else float('nan'):.2f} "
              f"median_latency={lat * 1000:.0f}ms")
    print(f'input tokens {tokens_in}, charged ${tokens_in * USD_PER_M_INPUT[args.model] / 1e6:.4f}; '
          f'ledger remaining ${remaining_usd(budget):.4f}')


if __name__ == '__main__':
    main()

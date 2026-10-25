"""D7: intent routing on eval/intent_v1 — the old pattern chain vs the decision model (Clef).

  python scripts/experiments/intent_eval.py eval/intent_v1/dev.jsonl [--out OUT.json] [--threshold 0.8]

For Clef, a prediction below the threshold goes to the general local-model path ("other"), as in the server
(dev run 1 showed the pattern fallback misrouting "知乎是什么网站"); raw and combined accuracy, with latency.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core import desktop_router as intent_router  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('data')
    ap.add_argument('--out')
    ap.add_argument('--threshold', type=float, default=0.8)
    args = ap.parse_args()
    rows = [json.loads(line) for line in open(args.data, encoding='utf-8') if line.strip()]
    results = []
    for row in rows:
        legacy = intent_router.legacy_intent(row['text'])
        clef = intent_router.classify(row['text'])
        if clef is None:
            raise SystemExit('decision model unavailable')
        # unsure -> the general local-model path ("other"); patterns only when the decision model is unavailable
        combined = clef['intent'] if clef['confidence'] >= args.threshold else 'other'
        results.append({**row, 'legacy': legacy, 'clef': clef['intent'], 'conf': round(clef['confidence'], 3),
                        'combined': combined, 'clef_day': clef['day'], 'legacy_day': intent_router.legacy_day(row['text']),
                        'latency_s': clef['latency_s']})
    n = len(results)
    for key in ('legacy', 'clef', 'combined'):
        ok = sum(r[key] == r['intent'] for r in results)
        print(f'{key:9s} {ok}/{n} = {ok / n:.2f}')
    cal = [r for r in results if r['intent'] == 'calendar']
    print(f"day (calendar rows): clef {sum(r['clef_day'] == r['day'] for r in cal)}/{len(cal)}  "
          f"legacy {sum(r['legacy_day'] == r['day'] for r in cal)}/{len(cal)}")
    print(f"latency median {statistics.median(r['latency_s'] for r in results):.2f}s  "
          f"max {max(r['latency_s'] for r in results):.2f}s; below threshold: {sum(r['conf'] < args.threshold for r in results)}")
    for r in results:
        if r['combined'] != r['intent'] or r['legacy'] != r['intent']:
            print(f"  {r['text'][:28]:30s} gold={r['intent']:13s} legacy={r['legacy']:13s} clef={r['clef']}({r['conf']}) -> {r['combined']}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()

"""General-ability spot check for a LoRA student (R3 acceptance: "general ability does not regress").

30 short questions with fixed answers (`eval/general_check_v1/questions.json`: arithmetic, units, facts, text,
JSON, Python, logic, instruction following, Chinese), asked to the local server at temperature 0 with no tools.
The adapter comes from KAGE_LORA exactly as for the benchmark runs, so the same script measures A0 and L3.

  python general_check.py --root OUT --port 18800
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_service import LORA, LocalService, write_json

QUESTIONS = ROOT / 'eval' / 'general_check_v1' / 'questions.json'


def normalise(text: str) -> str:
    return ' '.join(text.lower().replace('`', '').replace('**', '').split())


def passes(answer: str, accept: list[str]) -> bool:
    got = normalise(answer)
    return any(normalise(a) in got for a in accept)


def ask(port: int, prompt: str) -> str:
    body = json.dumps({'model': 'agents-a1-4b', 'temperature': 0, 'max_tokens': 200,
                       'messages': [{'role': 'user', 'content': prompt}]}).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions', data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())['choices'][0]['message'].get('content') or ''


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--port', type=int, default=18800)
    args = p.parse_args(argv)
    args.root.mkdir(parents=True, exist_ok=True)
    questions = json.loads(QUESTIONS.read_text())
    rows = []
    with LocalService(args.port, args.root):
        for q in questions:
            answer = ask(args.port, q['prompt'])
            rows.append({'id': q['id'], 'answer': answer[:400], 'passed': passes(answer, q['accept'])})
    with (args.root / 'results.jsonl').open('w') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    summary = {'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'lora': LORA}
    write_json(args.root / 'summary.json', summary)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()

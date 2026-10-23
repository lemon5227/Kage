"""R3d: give reasoning-free tool-call targets a short rationale instead of dropping them.

R3 (v26): the trained student wrote no reasoning before any tool call and lost the transfer families.
R3b (v29): dropping those targets restored transfer but removed most of the file families' solution-writing
steps (`write_file`: 202 without reasoning vs 101 with), and the in-family gain vanished. So keep every step and
fill the empty explanation (STaR-style rationalization): the teacher sees what the student saw (the task and the
recent turns) and the call it actually made, and writes one or two first-person sentences of why. The call itself
is never changed; a rationale that mentions hints, lessons or demonstrations, or is empty, is dropped (the row then
keeps its empty explanation and `r3_data --require-reasoning` still filters it).

Every call goes through the global teacher ledger (core/evolution/teacher_budget.py) and is cached by row hash, so
a rerun only pays for rows not yet done.

  python rationalize.py --sft R2.jsonl.gz [--sft ...] --out DIR [--cap-usd 0.5]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.budget import BudgetExhaustedError                      # noqa: E402
from core.evolution.teacher_budget import global_teacher_budget, remaining_usd  # noqa: E402

TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json').expanduser()
PROMPT = (
    'A small assistant model is solving a task with tools. You see the task, its most recent turns, and the tool '
    'call it made next. Write what the assistant would say right before that call: one or two short first-person '
    'sentences explaining why this call is the right next step. Use only information visible in the turns shown. '
    'Do not mention hints, lessons, examples, demonstrations, teachers or earlier tasks. Do not restate the whole '
    'tool arguments. Reply with the sentences only.'
)
BANNED = ('lesson', 'hint', 'demonstrat', 'teacher', 'earlier task', 'example task', 'guidance')
INPUT_TOKENS_CAP = 6000
OUTPUT_TOKENS = 160


def read_rows(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def reasonless(row: dict) -> bool:
    target = row.get('target') or {}
    return bool(target.get('tool_calls')) and not (target.get('content') or '').strip()


def _clip(text, n):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= n else text[:n // 2] + ' […] ' + text[-n // 2:]


def prompt_messages(row: dict) -> list[dict]:
    messages = row['messages']
    task = next((m['content'] for m in messages if m['role'] == 'user'), '')
    recent = [m for m in messages if m['role'] != 'system'][-4:]
    turns = '\n'.join(f"[{m['role']}] {_clip(m.get('content') or m.get('tool_calls') or '', 1200)}" for m in recent)
    call = row['target']['tool_calls'][0]['function']
    shown = {'name': call['name'], 'arguments': _clip(call.get('arguments'), 1500)}
    return [{'role': 'system', 'content': PROMPT},
            {'role': 'user', 'content': f'Task:\n{_clip(task, 2500)}\n\nRecent turns:\n{turns}\n\n'
                                        f'Next tool call:\n{json.dumps(shown, ensure_ascii=False)}'}]


def acceptable(text: str) -> bool:
    text = (text or '').strip()
    return 10 <= len(text) <= 600 and not any(word in text.lower() for word in BANNED)


def row_key(row: dict) -> str:
    return hashlib.sha256(json.dumps([row['messages'], row['target']], sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sft', type=Path, action='append', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--cap-usd', type=float, default=0.5)
    args = p.parse_args(argv)
    from core.model_provider import OpenAICompatibleProvider
    cloud = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']
    model = OpenAICompatibleProvider(api_key=cloud['api_key'], model_name=cloud['model_name'],
                                     base_url=cloud['base_url'], timeout_sec=60, thinking=False)
    budget = global_teacher_budget()
    start = remaining_usd(budget)
    args.out.mkdir(parents=True, exist_ok=True)
    cache_path = args.out / 'rationales.jsonl'
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            entry = json.loads(line)
            cache[entry['key']] = entry
    stats = {'rows': 0, 'reasonless': 0, 'filled': 0, 'rejected': 0, 'errors': 0, 'cached': 0}
    for path in args.sft:
        out_rows = []
        for row in read_rows(path):
            stats['rows'] += 1
            if reasonless(row):
                stats['reasonless'] += 1
                key = row_key(row)
                entry = cache.get(key)
                if entry is None:
                    if start - remaining_usd(budget) >= args.cap_usd:
                        raise SystemExit(f'cap ${args.cap_usd} reached; rerun with a higher --cap-usd to continue')
                    reservation = budget.reserve(INPUT_TOKENS_CAP, OUTPUT_TOKENS, call_type='rationale',
                                                 run_id=f'rationale-{key[:12]}')
                    response = None
                    try:
                        response = model.generate(messages=prompt_messages(row), max_tokens=OUTPUT_TOKENS,
                                                  temperature=0.0)
                    except BudgetExhaustedError:
                        raise
                    except Exception as exc:                       # network etc.: leave the row as it was
                        response = None
                        print(json.dumps({'error': type(exc).__name__}), flush=True)
                    finally:
                        budget.settle(reservation, getattr(response, 'usage', None))
                    text = (getattr(response, 'text', '') or '').strip() if response and not response.error else ''
                    entry = {'key': key, 'text': text, 'ok': acceptable(text), 'error': not text}
                    with cache_path.open('a') as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
                    cache[key] = entry
                else:
                    stats['cached'] += 1
                if entry['ok']:
                    row = {**row, 'target': {**row['target'], 'content': entry['text']}, 'rationalized': True}
                    stats['filled'] += 1
                elif entry['error']:
                    stats['errors'] += 1
                else:
                    stats['rejected'] += 1
            out_rows.append(row)
        name = path.name.replace('.jsonl.gz', '').replace('.jsonl', '') + '-rationalized.jsonl.gz'
        with gzip.open(args.out / name, 'wt', encoding='utf-8') as f:
            for row in out_rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
    stats['spent_usd'] = round(start - remaining_usd(budget), 4)
    stats['ledger_remaining_usd'] = round(remaining_usd(budget), 4)
    (args.out / 'rationalize-stats.json').write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats), flush=True)


if __name__ == '__main__':
    main()

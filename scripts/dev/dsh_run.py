"""Delegate one coding task to DeepSeek Harness (dsh headless) and account for it.

  python scripts/dev/dsh_run.py --cwd <dir> --task-file task.md [--log-dir artifacts/dsh] [--timeout 1800]

Workflow (user, 2026-10-18): Claude plans and reviews, dsh executes, to save Claude tokens.
- The DeepSeek key comes from the canonical teacher config and is placed only in this one child
  process's environment (DEEPSEEK_API_KEY); it is never printed, logged or written to disk.
- dsh runs with DSH_PERMISSION_MODE=workspace-write: it can write only under --cwd.
- Spend goes to a separate executor ledger (~/.kage/dsh_ledger.jsonl), NOT the Kage teacher ledger;
  the cap is US$2.00 (user, 2026-10-18). A run is refused once the cap is reached.
- Every run keeps the full event stream (<log-dir>/<run>.jsonl) for review.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

DSH = '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'
TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json').expanduser()
LEDGER = Path('~/.kage/dsh_ledger.jsonl').expanduser()
CAP_USD = 2.00
# DeepSeek flash list prices (same as core/evolution/teacher_budget.py). Cache-read tokens are charged
# at the full input price too: an upper bound (real cache hits are cheaper), so the cap stays safe.
INPUT_USD_PER_M, OUTPUT_USD_PER_M = 0.30, 1.20
# Only these variables reach dsh: nothing from Claude's own session (ANTHROPIC_*, CLAUDE_*, ...).
ENV_KEEP = ('PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LC_ALL', 'TMPDIR', 'TERM')


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(float(json.loads(l).get('usd', 0)) for l in LEDGER.read_text().splitlines() if l.strip())


def usage_of(events: list[dict]) -> dict:
    """Sum token usage over every event that reports it (field names vary by event type)."""
    total = {'input_tokens': 0, 'cache_read_tokens': 0, 'output_tokens': 0}
    for e in events:
        u = e.get('usage') if isinstance(e.get('usage'), dict) else None
        if not u or e.get('phase') != 'step_end':          # per-step usage; turn totals would double count
            continue
        total['input_tokens'] += int(u.get('inputTokens') or 0)
        total['cache_read_tokens'] += int(u.get('cacheReadTokens') or 0)
        total['output_tokens'] += int(u.get('outputTokens') or 0)
    return total


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cwd', type=Path, required=True)
    p.add_argument('--task-file', type=Path, required=True)
    p.add_argument('--log-dir', type=Path, default=Path('artifacts/dsh'))
    p.add_argument('--timeout', type=int, default=1800)
    p.add_argument('--session-id', help='continue an earlier dsh session (follow-up / review feedback)')
    args = p.parse_args(argv)
    before = spent()
    if before >= CAP_USD:
        print(f'refused: executor ledger at ${before:.4f} >= cap ${CAP_USD:.2f}', file=sys.stderr)
        return 2
    key = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']['api_key']
    env = {**{k: os.environ[k] for k in ENV_KEEP if k in os.environ},
           'DEEPSEEK_API_KEY': key, 'DSH_PERMISSION_MODE': 'workspace-write'}
    run = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log = args.log_dir / f'{run}.jsonl'
    cmd = [DSH, 'headless', '--json'] + (['--session-id', args.session_id] if args.session_id else []) + ['-']
    try:
        proc = subprocess.run(cmd, input=args.task_file.read_text(), cwd=args.cwd, env=env, capture_output=True,
                              text=True, timeout=args.timeout)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        err, code = f'timeout after {args.timeout}s', 124
    log.write_text(out.replace(key, '<redacted>'))
    (args.log_dir / f'{run}.stderr.txt').write_text(err.replace(key, '<redacted>'))
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    usage = usage_of(events)
    usd = ((usage['input_tokens'] + usage['cache_read_tokens']) * INPUT_USD_PER_M
           + usage['output_tokens'] * OUTPUT_USD_PER_M) / 1e6
    session = next((e.get('sessionId') or e.get('session_id') for e in events if e.get('sessionId') or e.get('session_id')), None)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open('a') as f:
        f.write(json.dumps({'run': run, 'cwd': str(args.cwd), 'task_file': str(args.task_file), 'exit': code,
                            **usage, 'usd': round(usd, 6), 'session': session}) + '\n')
    final = next((e.get('text', '') for e in reversed(events) if e.get('type') == 'final'), '')
    print(json.dumps({'run': run, 'exit': code, 'session': session, **usage, 'usd': round(usd, 4),
                      'ledger_usd': round(before + usd, 4), 'cap_usd': CAP_USD, 'log': str(log)}, ensure_ascii=False))
    print(final)
    return code


if __name__ == '__main__':
    sys.exit(main())

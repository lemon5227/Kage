"""Delegate one coding task to DeepSeek Harness (dsh headless) and account for it.

  python scripts/dev/dsh_run.py --cwd <dir> --task-file task.md [--log-dir artifacts/dsh] [--timeout 1800]

Workflow (user, 2026-10-18): Claude plans and reviews, dsh executes, to save Claude tokens.
- The DeepSeek key comes from the canonical teacher config and is placed only in this one child
  process's environment (DEEPSEEK_API_KEY); it is never printed, logged or written to disk.
- dsh runs with DSH_PERMISSION_MODE=workspace-write: it can write only under --cwd.
- Spend goes to a separate executor ledger (~/.kage/dsh_ledger.jsonl), NOT the Kage teacher ledger;
  the cap is US$2.00 (user, 2026-10-18). The cost booked is the drop in the DeepSeek account balance
  when one shows up right after the run (the balance lags), else the token estimate; while it runs, a token-based estimate stops dsh once it would
  pass the remaining cap (the first C3 run overshot a start-only check). A run is also refused when
  the account balance is below MIN_BALANCE_CNY (the account is shared with the Kage teacher).
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
# Live estimate only (the ledger records the measured balance drop): DeepSeek flash list prices, cache
# reads at a tenth of the input price.
INPUT_USD_PER_M, OUTPUT_USD_PER_M, CACHE_FACTOR = 0.30, 1.20, 0.1
CNY_PER_USD = 7.2
MIN_BALANCE_CNY = 3.0
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


def balance_cny(cloud: dict) -> float | None:
    import urllib.request
    try:
        req = urllib.request.Request(cloud['base_url'].rstrip('/') + '/user/balance',
                                     headers={'Authorization': 'Bearer ' + cloud['api_key']})
        infos = json.load(urllib.request.urlopen(req, timeout=20)).get('balance_infos', [])
        return float(next(i['total_balance'] for i in infos if i.get('currency') == 'CNY'))
    except Exception:                       # the measured cost is then missing, never invented
        return None


def estimate(usage: dict) -> float:
    return ((usage['input_tokens'] + CACHE_FACTOR * usage['cache_read_tokens']) * INPUT_USD_PER_M
            + usage['output_tokens'] * OUTPUT_USD_PER_M) / 1e6


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
    cloud = json.loads(TEACHER_CONFIG.read_text())['model']['cloud_api']
    key = cloud['api_key']
    start_balance = balance_cny(cloud)
    if start_balance is not None and start_balance < MIN_BALANCE_CNY:
        print(f'refused: DeepSeek balance CNY {start_balance:.2f} < {MIN_BALANCE_CNY}', file=sys.stderr)
        return 2
    env = {**{k: os.environ[k] for k in ENV_KEEP if k in os.environ},
           'DEEPSEEK_API_KEY': key, 'DSH_PERMISSION_MODE': 'workspace-write'}
    run = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log = args.log_dir / f'{run}.jsonl'
    cmd = [DSH, 'headless', '--json'] + (['--session-id', args.session_id] if args.session_id else []) + ['-']
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=args.cwd, env=env, text=True)
    proc.stdin.write(args.task_file.read_text())
    proc.stdin.close()
    events, stopped = [], ''
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=args.timeout)
    with log.open('w') as out:
        for line in proc.stdout:                       # stream: the cap is enforced during the run
            out.write(line.replace(key, '<redacted>'))
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
            if before + estimate(usage_of(events)) >= CAP_USD:
                stopped = f'stopped: estimated spend would pass the ${CAP_USD:.2f} cap'
            elif datetime.datetime.now() > deadline:
                stopped = f'timeout after {args.timeout}s'
            if stopped:
                proc.kill()
                break
    code = proc.wait() if not stopped else 124
    err = proc.stderr.read() if proc.stderr else ''
    (args.log_dir / f'{run}.stderr.txt').write_text((stopped + '\n' + err).replace(key, '<redacted>'))
    usage = usage_of(events)
    end_balance = balance_cny(cloud)
    # The balance updates with a delay (a small run showed no change): only a positive drop counts as
    # measured; otherwise the estimate is booked and both balances stay in the ledger for reconciling.
    measured = (round((start_balance - end_balance) / CNY_PER_USD, 6)
                if start_balance is not None and end_balance is not None and end_balance < start_balance else None)
    usd = measured if measured is not None else round(estimate(usage), 6)
    session = next((e.get('sessionId') or e.get('session_id') for e in events if e.get('sessionId') or e.get('session_id')), None)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open('a') as f:
        f.write(json.dumps({'run': run, 'cwd': str(args.cwd), 'task_file': str(args.task_file), 'exit': code,
                            **usage, 'usd': usd, 'measured': measured is not None,
                            'balance_cny': [start_balance, end_balance], 'session': session,
                            **({'stopped': stopped} if stopped else {})}) + '\n')
    final = next((e.get('text', '') for e in reversed(events) if e.get('type') == 'final'), '')
    print(json.dumps({'run': run, 'exit': code, 'session': session, **usage, 'usd': usd,
                      'measured': measured is not None, 'ledger_usd': round(before + usd, 4), 'cap_usd': CAP_USD,
                      'balance_cny': end_balance, 'log': str(log), **({'stopped': stopped} if stopped else {})},
                     ensure_ascii=False))
    print(final)
    return code


if __name__ == '__main__':
    sys.exit(main())

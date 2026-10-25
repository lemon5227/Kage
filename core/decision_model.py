"""Hosted decision model (Cloudflare Clef) for choices the local 4B model is slow or unreliable at.

Clef takes a state and typed questions (noul = yes/no probability, choice = one of named options with
calibrated probabilities) and answers in ~0.3–0.5 s (decision benchmark, `evidence/reports/decision-thx01/`).
It only chooses; it never writes text or acts. Callers keep a confidence threshold and fall back to the
local model below it.

Credentials: ~/.config/kage/teachers/cloudflare.json {account_id, api_token} (never printed or logged).
Every call is charged to the global teacher ledger at the list input price, free allocation or not.

It sits on the interactive path, so failure handling is strict: a short timeout (3 s, `decision_model.timeout_s`),
no retries, a circuit breaker (3 consecutive failures → skipped for 5 minutes) and a daily stop when the
provider reports its free allocation used up. Every one of these ends in DecisionUnavailable, and callers fall
back to the local model.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
import urllib.error
import urllib.request

MODEL = 'clef'
USD_PER_M_INPUT = 0.24
CREDENTIALS = Path('~/.config/kage/teachers/cloudflare.json').expanduser()


BREAKER_FAILURES, BREAKER_COOLDOWN_S = 3, 300
_breaker = {'failures': 0, 'open_until': 0.0, 'quota_day': ''}


class DecisionUnavailable(RuntimeError):
    pass


def available() -> bool:
    return _ready()


def _ready() -> bool:
    """Configured, under quota today, breaker closed (tests disable `available`, not this)."""
    if not CREDENTIALS.exists():
        return False
    if _breaker['quota_day'] == time.strftime('%Y-%m-%d', time.gmtime()):
        return False                            # free allocation used up today: never run into a bill
    return time.time() >= _breaker['open_until']


def _failed(kind: str) -> None:
    if kind == 'quota':
        _breaker['quota_day'] = time.strftime('%Y-%m-%d', time.gmtime())
        return
    _breaker['failures'] += 1
    if _breaker['failures'] >= BREAKER_FAILURES:
        _breaker['open_until'] = time.time() + BREAKER_COOLDOWN_S
        _breaker['failures'] = 0


def ask(state: str, questions: dict, *, run_id: str = 'decision', timeout: float | None = None) -> dict:
    """{qid: (answer, confidence, probabilities)}. questions: {qid: {'type': 'choice', 'question': str,
    'criteria': {name: description}}} or {'type': 'noul', 'question': str} (answer True/False)."""
    from core.config import get_config
    from core.evolution.teacher_budget import charge_external, global_teacher_budget
    if not available():
        raise DecisionUnavailable('decision model is paused (breaker open, quota used up, or not configured)')
    timeout = timeout or float(get_config('decision_model.timeout_s', 3.0))
    try:
        cred = json.loads(CREDENTIALS.read_text())
    except (OSError, ValueError) as exc:
        raise DecisionUnavailable('decision model is not configured') from exc
    url = f"https://api.cloudflare.com/client/v4/accounts/{cred['account_id']}/ai/run/@cf/cloudflare/{MODEL}"
    payload = {qid: {'type': q['type'], 'instructions': q['question'],
                     **({'criteria': q['criteria']} if q['type'] == 'choice' else {})} for qid, q in questions.items()}
    request = urllib.request.Request(url, method='POST', data=json.dumps(
        {'model': MODEL, 'state': state, 'questions': payload}).encode(), headers={
        'Authorization': f"Bearer {cred['api_token']}", 'Content-Type': 'application/json', 'User-Agent': 'kage/1'})
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors='replace')
        _failed('quota' if exc.code == 429 and 'FreeUsageLimit' in detail else 'error')
        raise DecisionUnavailable(f'decision model call failed: HTTP {exc.code}') from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        _failed('error')
        raise DecisionUnavailable(f'decision model call failed: {type(exc).__name__}') from exc
    _breaker['failures'] = 0
    result = body.get('result', body)
    usage = result.get('usage') or {}
    tokens = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
    charge_external(global_teacher_budget(), tokens * USD_PER_M_INPUT / 1e6, run_id=run_id, call_type='decision')
    answers = {}
    for qid, q in questions.items():
        a = (result.get('answers') or {}).get(qid) or {}
        if q['type'] == 'noul':
            p = float(a.get('noul', a.get('probability', a.get('yes', 0.5))))
            answers[qid] = (p >= 0.5, max(p, 1 - p), {'yes': p, 'no': 1 - p})
        else:
            probs = a.get('probabilities') or a.get('probs') or {}
            choice = a.get('choice') or a.get('answer') or (max(probs, key=probs.get) if probs else None)
            answers[qid] = (choice, float(probs.get(choice, 0.0)) if probs else 0.0, probs)
    answers['_latency_s'] = round(time.time() - started, 3)
    return answers

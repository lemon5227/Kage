"""Hosted decision model (Cloudflare Clef) for choices the local 4B model is slow or unreliable at.

Clef takes a state and typed questions (noul = yes/no probability, choice = one of named options with
calibrated probabilities) and answers in ~0.3–0.5 s (decision benchmark, `evidence/reports/decision-thx01/`).
It only chooses; it never writes text or acts. Callers keep a confidence threshold and fall back to the
local model below it.

Credentials: ~/.config/kage/teachers/cloudflare.json {account_id, api_token} (never printed or logged).
Every call is charged to the global teacher ledger at the list input price, free allocation or not.
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


class DecisionUnavailable(RuntimeError):
    pass


def available() -> bool:
    return CREDENTIALS.exists()


def ask(state: str, questions: dict, *, run_id: str = 'decision', timeout: float = 15) -> dict:
    """{qid: (answer, confidence, probabilities)}. questions: {qid: {'type': 'choice', 'question': str,
    'criteria': {name: description}}} or {'type': 'noul', 'question': str} (answer True/False)."""
    from core.evolution.teacher_budget import charge_external, global_teacher_budget
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
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise DecisionUnavailable(f'decision model call failed: {type(exc).__name__}') from exc
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

"""A3: the cloud teacher for real tasks, inside the global ledger and a daily cap.

When the user marks a task turn 👎, Kage offers to have the teacher redo it. Only after the user
accepts does ``LedgeredTeacher`` call DeepSeek: each call reserves its worst case in the global
teacher ledger first and is refused once today's real-use spend reaches the daily cap
(config ``evolution.real_teacher_daily_usd``, default US$0.05) — then Kage asks the user to
demonstrate instead. The key is read from the canonical teacher config and never logged.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import threading

from core.evolution.budget import BudgetExhaustedError
from core.evolution.teacher_budget import INPUT_USD_PER_M, OUTPUT_USD_PER_M, global_teacher_budget

TEACHER_CONFIG = Path('~/.config/kage/teachers/deepseek.json')
DAILY_STATE = Path('~/.kage/real_teacher_daily.json')
DEFAULT_DAILY_USD = 0.05
MAX_OUTPUT_TOKENS = 1024


class DailyCapReached(RuntimeError):
    """Today's real-use teacher allowance is spent; ask the user to demonstrate instead."""


def teacher_available(path: Path = TEACHER_CONFIG) -> bool:
    return Path(os.path.expanduser(str(path))).exists()


class LedgeredTeacher:
    def __init__(self, *, daily_usd: float = DEFAULT_DAILY_USD, inner=None, budget=None,
                 state_path: Path = DAILY_STATE, run_id: str = 'real-teacher'):
        if inner is None:
            from core.model_provider import OpenAICompatibleProvider
            cloud = json.loads(Path(os.path.expanduser(str(TEACHER_CONFIG))).read_text())['model']['cloud_api']
            inner = OpenAICompatibleProvider(api_key=cloud['api_key'], model_name=cloud['model_name'],
                                             base_url=cloud['base_url'], timeout_sec=int(cloud.get('timeout_sec', 120)),
                                             thinking=False)
        self.inner, self.daily_usd, self.run_id = inner, float(daily_usd), run_id
        self.budget = budget if budget is not None else global_teacher_budget()
        self.state_path = Path(os.path.expanduser(str(state_path)))
        self._lock = threading.Lock()
        self.model_name = getattr(inner, 'model_name', 'teacher')

    def spent_today(self) -> float:
        today = datetime.date.today().isoformat()
        if not self.state_path.exists():
            return 0.0
        state = json.loads(self.state_path.read_text())
        return float(state.get(today, 0.0))

    def _add_spend(self, usd: float) -> None:
        today = datetime.date.today().isoformat()
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        state = {today: round(float(state.get(today, 0.0)) + usd, 6)}       # keep only today
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state))

    def generate(self, messages, tools=None, max_tokens=MAX_OUTPUT_TOKENS, temperature=0.0, **kwargs):
        max_tokens = min(int(max_tokens or MAX_OUTPUT_TOKENS), MAX_OUTPUT_TOKENS)
        input_tokens = len(json.dumps({'messages': messages, 'tools': tools or []}, default=str)) // 3 + 64
        worst = input_tokens * INPUT_USD_PER_M / 1e6 + max_tokens * OUTPUT_USD_PER_M / 1e6
        with self._lock:
            if self.spent_today() + worst > self.daily_usd:
                raise DailyCapReached(f'real-use teacher allowance of ${self.daily_usd:.2f} for today is used up')
            try:
                reservation = self.budget.reserve(input_tokens, max_tokens, call_type='real_teacher', run_id=self.run_id)
            except BudgetExhaustedError as exc:
                raise DailyCapReached(f'global teacher ledger refused: {exc}') from exc
        response = None
        try:
            response = self.inner.generate(messages=messages, tools=tools, max_tokens=max_tokens, temperature=0.0)
        finally:
            usage = dict(getattr(response, 'usage', None) or {})
            self.budget.settle(reservation, usage or None)
            used = (usage.get('input_tokens', input_tokens) * INPUT_USD_PER_M
                    + usage.get('output_tokens', max_tokens) * OUTPUT_USD_PER_M) / 1e6
            with self._lock:
                self._add_spend(used)
        return response

    def __getattr__(self, name):
        return getattr(self.inner, name)

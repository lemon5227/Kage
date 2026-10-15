"""One global teacher ledger shared by every experiment (user cap: US$1 on 2026-10-14, raised to US$2 on 2026-10-15).

All cloud-teacher calls (demonstrations, skill extraction, architect proposals,
challenger tasks) must reserve through ``global_teacher_budget()`` so that a new
experiment directory can never reset the total. Prices are the conservative
cache-miss DeepSeek rates frozen in earlier reports; cache hits only lower cost.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.evolution.budget import BudgetConfig, BudgetTracker

GLOBAL_TEACHER_CAP_USD = 2.00
INPUT_USD_PER_M = 0.30
OUTPUT_USD_PER_M = 1.20
DEFAULT_LEDGER = Path('~/.config/kage/teachers/ledger.sqlite')


def ledger_path() -> Path:
    return Path(os.environ.get('KAGE_TEACHER_LEDGER', str(DEFAULT_LEDGER))).expanduser()


def global_teacher_budget(cap_usd: float | None = None) -> BudgetTracker:
    # A remote host (e.g. Kaggle) starts with an empty ledger, so it runs under the allocation it was
    # given (KAGE_TEACHER_CAP_USD) and its spend is charged back to the home ledger afterwards.
    if cap_usd is None:
        cap_usd = float(os.environ.get('KAGE_TEACHER_CAP_USD', GLOBAL_TEACHER_CAP_USD))
    if not 0 < cap_usd <= GLOBAL_TEACHER_CAP_USD:
        raise ValueError(f'teacher cap must be in (0, {GLOBAL_TEACHER_CAP_USD}] USD')
    config = BudgetConfig(max_input_tokens_total=50_000_000, max_output_tokens_total=5_000_000,
                          max_api_calls=5_000, max_cost_usd=cap_usd,
                          input_cost_per_million=INPUT_USD_PER_M, output_cost_per_million=OUTPUT_USD_PER_M)
    return BudgetTracker(config, ledger_path())


def remaining_usd(tracker: BudgetTracker) -> float:
    tracker._load_totals()
    return max(0.0, (tracker.config.max_cost_usd or 0.0) - tracker.total_cost_usd)


def charge_external(tracker: BudgetTracker, usd: float, *, run_id: str, call_type: str = 'external') -> None:
    """Record spend that happened outside this ledger (e.g. a scheduler search subprocess).

    The cost is booked as output tokens at the ledger's output price, so the US$ total stays exact.
    """
    if usd <= 0:
        return
    tokens = max(1, round(usd / OUTPUT_USD_PER_M * 1_000_000))
    reservation = tracker.reserve(1, tokens, call_type=call_type, run_id=run_id)
    tracker.settle(reservation, {'input_tokens': 0, 'output_tokens': tokens, 'api_calls': 1})

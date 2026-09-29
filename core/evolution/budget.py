"""
Budget tracking and reservation management for Kage EvoLab.
Strict token, call count, and cost accounting following Section 7 of master plan v2.1.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class BudgetExhaustedError(RuntimeError):
    """Raised when an operation would exceed allowed budget limits."""
    pass


@dataclass
class Reservation:
    reservation_id: str
    input_cap: int
    output_cap: int
    call_type: str  # 'execution' | 'optimizer'
    created_at: float
    settled: bool = False
    actual_input: int = 0
    actual_output: int = 0


@dataclass
class BudgetConfig:
    max_input_tokens_total: int = 1_000_000
    max_output_tokens_total: int = 200_000
    max_api_calls: int = 500
    max_cost_usd: float | None = None
    input_cost_per_million: float = 0.27  # e.g., standard pricing reference
    output_cost_per_million: float = 1.10


class BudgetTracker:
    """
    Thread-safe / deterministic budget accounting with two-phase reservation & settlement.
    Supports conservative settlement for incomplete or crashed calls.
    """

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig()
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_api_calls: int = 0
        self.total_cost_usd: float = 0.0

        # Sub-accounts for attribution
        self.usage_by_type: dict[str, dict[str, int]] = {
            "execution": {"input": 0, "output": 0, "calls": 0},
            "optimizer": {"input": 0, "output": 0, "calls": 0},
        }

        # Active reservations: reservation_id -> Reservation
        self._active_reservations: dict[str, Reservation] = {}

    @property
    def reserved_input_tokens(self) -> int:
        return sum(r.input_cap for r in self._active_reservations.values() if not r.settled)

    @property
    def reserved_output_tokens(self) -> int:
        return sum(r.output_cap for r in self._active_reservations.values() if not r.settled)

    def can_reserve(self, input_cap: int, output_cap: int) -> bool:
        """Query if the requested caps can be reserved without exceeding total budget."""
        if self.total_api_calls + len(self._active_reservations) + 1 > self.config.max_api_calls:
            return False

        committed_input = self.total_input_tokens + self.reserved_input_tokens + input_cap
        if committed_input > self.config.max_input_tokens_total:
            return False

        committed_output = self.total_output_tokens + self.reserved_output_tokens + output_cap
        if committed_output > self.config.max_output_tokens_total:
            return False

        if self.config.max_cost_usd is not None:
            est_cost = (
                committed_input * (self.config.input_cost_per_million / 1_000_000.0)
                + committed_output * (self.config.output_cost_per_million / 1_000_000.0)
            )
            if est_cost > self.config.max_cost_usd:
                return False

        return True

    def reserve(self, input_cap: int, output_cap: int, call_type: str = "execution") -> str:
        """Reserve token bounds for an upcoming API call."""
        if not self.can_reserve(input_cap, output_cap):
            raise BudgetExhaustedError(
                f"Cannot reserve input={input_cap}, output={output_cap}. "
                f"Committed: input={self.total_input_tokens + self.reserved_input_tokens}/{self.config.max_input_tokens_total}, "
                f"output={self.total_output_tokens + self.reserved_output_tokens}/{self.config.max_output_tokens_total}"
            )

        res_id = str(uuid.uuid4())
        reservation = Reservation(
            reservation_id=res_id,
            input_cap=input_cap,
            output_cap=output_cap,
            call_type=call_type,
            created_at=time.time(),
        )
        self._active_reservations[res_id] = reservation
        return res_id

    def settle(self, reservation_id: str, actual_usage: dict[str, Any] | None = None) -> None:
        """
        Settle a reservation with actual usage.
        If actual_usage is None or missing counts, settles conservatively at full reservation cap.
        """
        res = self._active_reservations.pop(reservation_id, None)
        if not res:
            return  # Already settled or invalid

        if actual_usage is not None:
            actual_in = int(actual_usage.get("input_tokens") or actual_usage.get("prompt_tokens") or 0)
            actual_out = int(actual_usage.get("output_tokens") or actual_usage.get("completion_tokens") or 0)
        else:
            # Conservative settlement
            actual_in = res.input_cap
            actual_out = res.output_cap

        # Update totals
        self.total_input_tokens += actual_in
        self.total_output_tokens += actual_out
        self.total_api_calls += 1

        cost = (
            actual_in * (self.config.input_cost_per_million / 1_000_000.0)
            + actual_out * (self.config.output_cost_per_million / 1_000_000.0)
        )
        self.total_cost_usd += cost

        # Attribute to call type
        ctype = res.call_type if res.call_type in self.usage_by_type else "execution"
        self.usage_by_type[ctype]["input"] += actual_in
        self.usage_by_type[ctype]["output"] += actual_out
        self.usage_by_type[ctype]["calls"] += 1

    def to_dict(self) -> dict[str, Any]:
        """Export current usage snapshot."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_api_calls": self.total_api_calls,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "usage_by_type": self.usage_by_type,
            "active_reservations": len(self._active_reservations),
        }

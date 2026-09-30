"""
Budget tracking and reservation management for Kage EvoLab.
Strict token, call count, and cost accounting following Section 7 of master plan v2.1.
"""

from __future__ import annotations

import time
import uuid
import sqlite3
from dataclasses import dataclass
from pathlib import Path
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
    run_id: str | None = None
    settled: bool = False
    actual_input: int = 0
    actual_output: int = 0
    api_call_cap: int = 1


@dataclass
class BudgetConfig:
    max_input_tokens_total: int = 1_000_000
    max_output_tokens_total: int = 200_000
    max_api_calls: int = 500
    max_cost_usd: float | None = None
    input_cost_per_million: float = 0.27  # illustrative rate, not a live quote
    output_cost_per_million: float = 1.10


class BudgetTracker:
    """
    Single-worker deterministic budget accounting with two-phase reservation & settlement.
    Supports conservative settlement for incomplete or crashed calls.
    """

    def __init__(self, config: BudgetConfig | None = None, db_path: str | Path | None = None) -> None:
        self.config = config or BudgetConfig()
        self.db_path = Path(db_path) if db_path is not None else None
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
        self._run_usage: dict[str, dict[str, int]] = {}
        self.interrupted_run_ids: set[str] = set()
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS evolution_budget (
                    reservation_id TEXT PRIMARY KEY, run_id TEXT, call_type TEXT NOT NULL,
                    input_cap INTEGER NOT NULL, output_cap INTEGER NOT NULL,
                    input_used INTEGER, output_used INTEGER, state TEXT NOT NULL,
                    created_at REAL NOT NULL
                )""")
                columns = {row[1] for row in conn.execute("PRAGMA table_info(evolution_budget)")}
                if "call_cap" not in columns:
                    conn.execute("ALTER TABLE evolution_budget ADD COLUMN call_cap INTEGER NOT NULL DEFAULT 1")
                if "calls_used" not in columns:
                    conn.execute("ALTER TABLE evolution_budget ADD COLUMN calls_used INTEGER")
                    conn.execute("UPDATE evolution_budget SET calls_used = 1 WHERE state != 'pending'")
                pending = conn.execute("SELECT run_id FROM evolution_budget WHERE state = 'pending'").fetchall()
                self.interrupted_run_ids = {row[0] for row in pending if row[0]}
                # A request may have reached the provider before process termination.
                conn.execute("""UPDATE evolution_budget SET input_used = input_cap,
                    output_used = output_cap, calls_used = call_cap, state = 'unknown' WHERE state = 'pending'""")
            self._load_totals()

    def _connection(self) -> sqlite3.Connection:
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _load_totals(self) -> None:
        assert self.db_path is not None
        with self._connection() as conn:
            rows = conn.execute("""SELECT call_type, input_used, output_used, COALESCE(calls_used, 1) FROM evolution_budget
                WHERE state IN ('settled', 'unknown')""").fetchall()
        self.total_input_tokens = sum(row[1] for row in rows)
        self.total_output_tokens = sum(row[2] for row in rows)
        self.total_api_calls = sum(row[3] for row in rows)
        self.total_cost_usd = (
            self.total_input_tokens * self.config.input_cost_per_million
            + self.total_output_tokens * self.config.output_cost_per_million
        ) / 1_000_000
        self.usage_by_type = {key: {"input": 0, "output": 0, "calls": 0} for key in ("execution", "optimizer")}
        for kind, input_used, output_used, calls_used in rows:
            account = self.usage_by_type.get(kind, self.usage_by_type["execution"])
            account["input"] += input_used
            account["output"] += output_used
            account["calls"] += calls_used

    @property
    def reserved_input_tokens(self) -> int:
        return sum(r.input_cap for r in self._active_reservations.values() if not r.settled)

    @property
    def reserved_output_tokens(self) -> int:
        return sum(r.output_cap for r in self._active_reservations.values() if not r.settled)

    def can_reserve(self, input_cap: int, output_cap: int, api_call_cap: int = 1) -> bool:
        if input_cap <= 0 or output_cap <= 0 or api_call_cap <= 0:
            return False
        if self.db_path is not None:
            self._load_totals()
        """Query if the requested caps can be reserved without exceeding total budget."""
        if self.total_api_calls + sum(r.api_call_cap for r in self._active_reservations.values()) + api_call_cap > self.config.max_api_calls:
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

    def reserve(self, input_cap: int, output_cap: int, call_type: str = "execution", run_id: str | None = None, api_call_cap: int = 1) -> str:
        """Reserve token bounds for an upcoming API call."""
        if not self.can_reserve(input_cap, output_cap, api_call_cap):
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
            run_id=run_id,
            api_call_cap=api_call_cap,
        )
        self._active_reservations[res_id] = reservation
        if self.db_path is not None:
            with self._connection() as conn:
                conn.execute("""INSERT INTO evolution_budget
                    (reservation_id, run_id, call_type, input_cap, output_cap, state, created_at, call_cap)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (res_id, run_id, call_type, input_cap, output_cap, reservation.created_at, api_call_cap))
        return res_id

    def settle(self, reservation_id: str, actual_usage: dict[str, Any] | None = None) -> None:
        """
        Settle a reservation with actual usage.
        If actual_usage is None or missing counts, settles conservatively at full reservation cap.
        """
        res = self._active_reservations.pop(reservation_id, None)
        if not res:
            return  # Already settled or invalid

        if actual_usage is not None and (
            ("input_tokens" in actual_usage or "prompt_tokens" in actual_usage)
            and ("output_tokens" in actual_usage or "completion_tokens" in actual_usage)
        ):
            try:
                actual_in = int(actual_usage.get("input_tokens", actual_usage.get("prompt_tokens")))
                actual_out = int(actual_usage.get("output_tokens", actual_usage.get("completion_tokens")))
                if actual_in < 0 or actual_out < 0:
                    raise ValueError("negative token usage")
            except (TypeError, ValueError):
                actual_in, actual_out = res.input_cap, res.output_cap
        else:
            # Conservative settlement
            actual_in = res.input_cap
            actual_out = res.output_cap

        # Update totals
        try:
            actual_calls = int(actual_usage.get("api_calls", res.api_call_cap)) if actual_usage is not None else res.api_call_cap
            if actual_calls < 0:
                raise ValueError("negative call usage")
        except (TypeError, ValueError):
            actual_calls = res.api_call_cap
        self.total_input_tokens += actual_in
        self.total_output_tokens += actual_out
        self.total_api_calls += actual_calls

        cost = (
            actual_in * (self.config.input_cost_per_million / 1_000_000.0)
            + actual_out * (self.config.output_cost_per_million / 1_000_000.0)
        )
        self.total_cost_usd += cost

        # Attribute to call type
        ctype = res.call_type if res.call_type in self.usage_by_type else "execution"
        self.usage_by_type[ctype]["input"] += actual_in
        self.usage_by_type[ctype]["output"] += actual_out
        self.usage_by_type[ctype]["calls"] += actual_calls
        if res.run_id is not None:
            usage = self._run_usage.setdefault(res.run_id, {"input_tokens": 0, "output_tokens": 0})
            usage["input_tokens"] += actual_in
            usage["output_tokens"] += actual_out
            usage["api_calls"] = usage.get("api_calls", 0) + actual_calls
        if self.db_path is not None:
            with self._connection() as conn:
                conn.execute("""UPDATE evolution_budget SET input_used = ?, output_used = ?,
                    calls_used = ?, state = 'settled' WHERE reservation_id = ?""",
                    (actual_in, actual_out, actual_calls, reservation_id))

    def get_run_usage(self, run_id: str) -> dict[str, int]:
        if self.db_path is None:
            return dict(self._run_usage.get(run_id, {"input_tokens": 0, "output_tokens": 0}))
        with self._connection() as conn:
            row = conn.execute("""SELECT COALESCE(SUM(input_used), 0),
                COALESCE(SUM(output_used), 0), COALESCE(SUM(calls_used), 0) FROM evolution_budget
                WHERE run_id = ? AND state IN ('settled', 'unknown')""", (run_id,)).fetchone()
        return {"input_tokens": int(row[0]), "output_tokens": int(row[1]), "api_calls": int(row[2])}

    def forget_run(self, run_id: str) -> int:
        """Drop persisted accounting for a run that is going to be retried.

        Only for explicit retries of infrastructure failures: a crashed call was
        settled conservatively at its cap, and re-running the measurement must not
        double-charge the budget. Returns the number of reservation rows removed.
        """
        if self.db_path is None:
            self._run_usage.pop(run_id, None)
            self.interrupted_run_ids.discard(run_id)
            return 0
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM evolution_budget WHERE run_id = ?", (run_id,))
            removed = cursor.rowcount
        self.interrupted_run_ids.discard(run_id)
        self._run_usage.pop(run_id, None)
        self._load_totals()
        return int(removed or 0)

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

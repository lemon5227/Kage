"""
Persistent SQLite-backed experiment journal for Kage EvoLab.
Records event streams, run completions, and ensures idempotent resume as specified in master plan v2.1.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.evolution.contracts import EvolutionEvent, RunResult, RunStatus


class Journal:
    """
    Manages structured persistence for evolution runs and step-level event streams.
    Ensures idempotent recording and enables resuming interrupted experiments.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    trace_path TEXT NOT NULL,
                    usage_json TEXT NOT NULL,
                    final_state_path TEXT NOT NULL,
                    progress_stagnant INTEGER NOT NULL DEFAULT 0,
                    rollback_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    usage_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_run_id ON events (run_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_candidate ON runs (candidate_id);")

    def is_run_completed(self, run_id: str) -> bool:
        """Check if a specific run has already completed and recorded its final state."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM runs WHERE run_id = ? LIMIT 1;", (run_id,))
            return cursor.fetchone() is not None

    def get_completed_run_ids(self) -> set[str]:
        """Return the set of all completed run IDs to allow quick resume filtering."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT run_id FROM runs;")
            return {row["run_id"] for row in cursor.fetchall()}

    def record_run_completion(
        self,
        result: RunResult,
        candidate_id: str,
        task_id: str,
    ) -> None:
        """Idempotently insert or update a run result."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, candidate_id, task_id, status, score,
                    trace_path, usage_json, final_state_path,
                    progress_stagnant, rollback_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    result.run_id,
                    candidate_id,
                    task_id,
                    result.status,
                    result.score,
                    result.trace_path,
                    json.dumps(result.usage),
                    result.final_state_path,
                    1 if result.progress_stagnant else 0,
                    result.rollback_count,
                    time.time(),
                ),
            )

    def record_event(self, event: EvolutionEvent) -> None:
        """Record an execution or diagnostic event in the step-level journal."""
        ts = event.timestamp if event.timestamp > 0 else time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    run_id, candidate_id, task_id, step, event_type,
                    payload_json, usage_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.run_id,
                    event.candidate_id,
                    event.task_id,
                    event.step,
                    event.event_type,
                    json.dumps(event.payload),
                    json.dumps(event.usage),
                    ts,
                ),
            )

    def get_run(self, run_id: str) -> RunResult | None:
        """Retrieve recorded RunResult by run_id."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM runs WHERE run_id = ? LIMIT 1;", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return RunResult(
                run_id=row["run_id"],
                status=row["status"],  # type: ignore
                score=row["score"],
                trace_path=row["trace_path"],
                usage=json.loads(row["usage_json"]),
                final_state_path=row["final_state_path"],
                progress_stagnant=bool(row["progress_stagnant"]),
                rollback_count=row["rollback_count"],
            )

    def get_events(self, run_id: str) -> list[EvolutionEvent]:
        """Retrieve all events belonging to a run in chronological order."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY id ASC;",
                (run_id,),
            )
            events = []
            for row in cursor.fetchall():
                events.append(
                    EvolutionEvent(
                        run_id=row["run_id"],
                        candidate_id=row["candidate_id"],
                        task_id=row["task_id"],
                        step=row["step"],
                        event_type=row["event_type"],
                        payload=json.loads(row["payload_json"]),
                        usage=json.loads(row["usage_json"]),
                        timestamp=row["timestamp"],
                    )
                )
            return events

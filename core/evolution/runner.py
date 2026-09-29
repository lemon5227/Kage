"""
Execution runner and deterministic evaluator for Kage EvoLab.
Provides process/workspace isolation, timeout handling, budget integration,
and progress observation per master plan v2.1.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from core.evolution.budget import BudgetExhaustedError, BudgetTracker
from core.evolution.contracts import Candidate, EvolutionEvent, RunResult, RunSpec, RunStatus
from core.evolution.journal import Journal
from core.evolution.progress import ProgressTracker


class Evaluator:
    """Deterministic, external task scoring engine."""

    @staticmethod
    def score(task_def: dict[str, Any], workspace_dir: Path) -> float:
        criteria = task_def.get("scoring_criteria", {})
        ctype = criteria.get("type")
        target_file = criteria.get("file")

        if not target_file:
            return 0.0

        output_path = workspace_dir / target_file
        if not output_path.exists():
            return 0.0

        if ctype == "json_exact_match":
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    actual = json.load(f)
                expected = criteria.get("expected")
                if actual == expected:
                    return 1.0
                # Granular partial score if both are lists
                if isinstance(actual, list) and isinstance(expected, list) and len(expected) > 0:
                    matched = sum(1 for item in actual if item in expected)
                    return round(matched / len(expected), 2)
                return 0.0
            except Exception:
                return 0.0

        return 0.0


class FakeEvolutionProvider:
    """
    Deterministic simulated provider for zero-cost testing of execution loops,
    progress tracking, budget exhaustion, and error recovery.
    """

    def __init__(self, mode: str = "baseline") -> None:
        self.mode = mode
        self.calls: int = 0
        self.call_log: list[dict[str, Any]] = []

    def generate_step(
        self,
        task_def: dict[str, Any],
        step: int,
        history: list[dict[str, Any]],
        workspace_dir: Path,
    ) -> dict[str, Any]:
        """Produce the next action dictionary and simulated token usage."""
        self.calls += 1
        task_id = task_def.get("task_id", "")
        self.call_log.append({"task_id": task_id, "step": step})

        usage = {"input_tokens": 120, "output_tokens": 45}

        # Stagnant loop simulation mode
        if self.mode == "stagnant":
            return {
                "action": {"name": "read_file", "path": "raw_records.json"},
                "usage": usage,
            }

        # Normal deterministic task simulation
        if task_id == "smoke_normalize_fields":
            if step == 1:
                return {
                    "action": {"name": "read_file", "path": "raw_records.json"},
                    "usage": usage,
                }
            elif step == 2:
                # Write normalized records
                normalized = [
                    {"id": 101, "name": "Alice Smith", "score": 95.5},
                    {"id": 102, "name": "Bob Jones", "score": 88.0},
                ]
                return {
                    "action": {
                        "name": "write_file",
                        "path": "normalized_records.json",
                        "content": json.dumps(normalized, indent=2),
                    },
                    "usage": usage,
                }
            else:
                return {"action": {"name": "finish"}, "usage": usage}

        elif task_id == "smoke_missing_field":
            if step == 1:
                return {
                    "action": {"name": "read_file", "path": "incomplete_records.json"},
                    "usage": usage,
                }
            elif step == 2:
                if self.mode == "fixed":
                    # Fixed version correctly fills in missing score
                    validated = [
                        {"id": 201, "name": "Charlie", "score": 0.0},
                        {"id": 202, "name": "David", "score": 72.0},
                    ]
                    return {
                        "action": {
                            "name": "write_file",
                            "path": "validated_records.json",
                            "content": json.dumps(validated, indent=2),
                        },
                        "usage": usage,
                    }
                else:
                    # Baseline mode misses the missing field handling
                    incomplete = [
                        {"id": 201, "name": "Charlie"},
                        {"id": 202, "name": "David", "score": 72.0},
                    ]
                    return {
                        "action": {
                            "name": "write_file",
                            "path": "validated_records.json",
                            "content": json.dumps(incomplete, indent=2),
                        },
                        "usage": usage,
                    }
            else:
                return {"action": {"name": "finish"}, "usage": usage}

        return {"action": {"name": "finish"}, "usage": usage}


class EvolutionRunner:
    """
    Orchestrates candidate evaluation runs on individual tasks.
    Manages isolated workspace lifecycle, progress tracking, budget bounds, and journaling.
    """

    def __init__(
        self,
        journal: Journal,
        budget: BudgetTracker,
        base_dir: str | Path | None = None,
        provider: Any = None,
    ) -> None:
        self.journal = journal
        self.budget = budget
        self.base_dir = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "kage_evolution"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or FakeEvolutionProvider()
        self.evaluator = Evaluator()

    def _setup_workspace(self, run_id: str, task_def: dict[str, Any]) -> Path:
        """Create a clean isolated workspace and populate initial fixtures."""
        ws = self.base_dir / f"run_{run_id}"
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True, exist_ok=True)

        for filename, content in task_def.get("initial_files", {}).items():
            file_path = ws / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        return ws

    def _cleanup_workspace(self, workspace_dir: Path) -> None:
        """Cleanly remove workspace to ensure no leakage between runs."""
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def _execute_tool_action(self, action: dict[str, Any], workspace_dir: Path) -> dict[str, Any]:
        """Execute local filesystem tool action in the isolated workspace."""
        name = action.get("name")
        if name == "read_file":
            rel_path = action.get("path", "")
            target = workspace_dir / rel_path
            if target.exists():
                try:
                    with open(target, "r", encoding="utf-8") as f:
                        return {"status": "ok", "content": f.read()}
                except Exception as e:
                    return {"status": "error", "message": str(e)}
            return {"status": "error", "message": f"File not found: {rel_path}"}

        elif name == "write_file":
            rel_path = action.get("path", "")
            content = action.get("content", "")
            target = workspace_dir / rel_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(content)
                return {"status": "ok", "bytes_written": len(content.encode("utf-8"))}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        elif name == "finish":
            return {"status": "finished"}

        return {"status": "unknown_action", "action": name}

    def run(
        self,
        candidate: Candidate,
        task_def: dict[str, Any],
        spec: RunSpec,
        retain_workspace: bool = True,
    ) -> RunResult:
        """
        Execute task run synchronously with budget checks, progress observation, and evaluation.
        If already completed in journal, skips execution to preserve budget.
        """
        # 1. Check if already completed in journal (Idempotent Resume)
        if self.journal.is_run_completed(spec.run_id):
            cached = self.journal.get_run(spec.run_id)
            if cached is not None:
                return cached

        # 2. Setup isolated workspace
        ws = self._setup_workspace(spec.run_id, task_def)
        progress = ProgressTracker()
        history: list[dict[str, Any]] = []
        step_events: list[dict[str, Any]] = []
        total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        status: RunStatus = "failed"
        stagnant_detected = False
        start_time = time.time()

        try:
            for step in range(1, spec.max_steps + 1):
                # Check timeout
                if time.time() - start_time > spec.timeout_s:
                    status = "timeout"
                    break

                # Reserve budget for model call
                res_id = None
                try:
                    res_id = self.budget.reserve(input_cap=2000, output_cap=1000, call_type="execution")
                except BudgetExhaustedError:
                    status = "budget_exhausted"
                    self.journal.record_event(
                        EvolutionEvent(
                            run_id=spec.run_id,
                            candidate_id=candidate.candidate_id,
                            task_id=spec.task_id,
                            step=step,
                            event_type="budget_stop",
                            payload={"reason": "budget_exhausted"},
                        )
                    )
                    break

                # Model step invocation
                try:
                    step_out = self.provider.generate_step(task_def, step, history, ws)
                    action = step_out.get("action", {})
                    call_usage = step_out.get("usage", {})
                    self.budget.settle(res_id, call_usage)
                except Exception as ex:
                    # Settle conservatively upon error
                    self.budget.settle(res_id, None)
                    status = "crashed"
                    break

                total_usage["input_tokens"] += call_usage.get("input_tokens", 0)
                total_usage["output_tokens"] += call_usage.get("output_tokens", 0)

                # Record Action Event
                self.journal.record_event(
                    EvolutionEvent(
                        run_id=spec.run_id,
                        candidate_id=candidate.candidate_id,
                        task_id=spec.task_id,
                        step=step,
                        event_type="action",
                        payload={"action": action},
                        usage=call_usage,
                    )
                )

                if action.get("name") == "finish":
                    break

                # Tool Execution
                obs = self._execute_tool_action(action, ws)
                history.append({"step": step, "action": action, "observation": obs})

                # Record Observation Event
                self.journal.record_event(
                    EvolutionEvent(
                        run_id=spec.run_id,
                        candidate_id=candidate.candidate_id,
                        task_id=spec.task_id,
                        step=step,
                        event_type="observation",
                        payload={"observation": obs},
                    )
                )

                # Progress observation
                prog_result = progress.observe(action, obs)
                if prog_result["stagnant"]:
                    stagnant_detected = True
                    self.journal.record_event(
                        EvolutionEvent(
                            run_id=spec.run_id,
                            candidate_id=candidate.candidate_id,
                            task_id=spec.task_id,
                            step=step,
                            event_type="stagnation",
                            payload=prog_result,
                        )
                    )

            # 3. Deterministic Evaluation
            score = self.evaluator.score(task_def, ws)
            if status not in ("timeout", "budget_exhausted", "crashed"):
                status = "passed" if score >= 1.0 else "failed"

            # Save trace
            trace_path = str(ws / "trace.jsonl")
            with open(trace_path, "w", encoding="utf-8") as f:
                for h in history:
                    f.write(json.dumps(h) + "\n")

            result = RunResult(
                run_id=spec.run_id,
                status=status,
                score=score,
                trace_path=trace_path,
                usage=total_usage,
                final_state_path=str(ws),
                progress_stagnant=stagnant_detected,
                rollback_count=0,
            )

            # Record completion in journal
            self.journal.record_run_completion(result, candidate.candidate_id, spec.task_id)
            return result

        finally:
            if not retain_workspace:
                self._cleanup_workspace(ws)

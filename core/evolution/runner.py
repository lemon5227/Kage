"""
Execution runner and deterministic evaluator for Kage EvoLab.
Provides process/workspace isolation, timeout handling, budget integration,
and progress observation per master plan v2.1.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import re
import signal
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from core.evolution.budget import BudgetExhaustedError, BudgetTracker
from core.evolution.contracts import Candidate, EvolutionEvent, RunResult, RunSpec, RunStatus
from core.evolution.journal import Journal
from core.evolution.progress import ProgressTracker


class StepTimeoutError(TimeoutError):
    pass


def _workspace_file(workspace_dir: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("workspace path must be relative")
    root = workspace_dir.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("workspace path escapes task directory")
    return target


def _provider_worker(provider: Any, task_def: dict[str, Any], step: int,
                     history: list[dict[str, Any]], workspace_dir: Path, pipe: Any) -> None:
    """One process group per model step, so a timeout can stop descendants too."""
    try:
        if hasattr(os, "setsid"):
            os.setsid()
        result = provider.generate_step(task_def, step, history, workspace_dir)
        pipe.send(("ok", result, getattr(provider, "calls", None), getattr(provider, "call_log", None)))
    except BaseException as exc:
        pipe.send(("error", f"{type(exc).__name__}: {exc}", None, None))
    finally:
        pipe.close()


class Evaluator:
    """Deterministic, external task scoring engine."""

    @staticmethod
    def score(task_def: dict[str, Any], workspace_dir: Path) -> float:
        criteria = task_def.get("scoring_criteria", {})
        ctype = criteria.get("type")
        target_file = criteria.get("file")

        if not target_file:
            return 0.0

        try:
            output_path = _workspace_file(workspace_dir, target_file)
        except ValueError:
            return 0.0
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
                    # A duplicate output must not match the same expected item twice.
                    remaining = expected.copy()
                    matched = 0
                    for item in actual:
                        if item in remaining:
                            remaining.remove(item)
                            matched += 1
                    precision_recall_score = 2 * matched / (len(actual) + len(expected))
                    return min(0.99, round(precision_recall_score, 2))
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
                raw = json.loads((workspace_dir / "raw_records.json").read_text())
                normalized = [
                    {"id": row["ID"], "name": row["Full_Name"], "score": row["Points"]}
                    for row in raw
                ]
                return {
                    "action": {
                        "name": "write_file",
                        "path": task_def.get("output_file", "normalized_records.json"),
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
                    raw = json.loads((workspace_dir / "incomplete_records.json").read_text())
                    validated = [dict(row, score=row.get("score", 0.0)) for row in raw]
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
                    incomplete = json.loads((workspace_dir / "incomplete_records.json").read_text())
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
        step_isolation: str = "fork",
    ) -> None:
        self.journal = journal
        self.budget = budget
        self.base_dir = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "kage_evolution"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or FakeEvolutionProvider()
        self.evaluator = Evaluator()
        if step_isolation not in ("fork", "inline"):
            raise ValueError("step_isolation must be 'fork' or 'inline'")
        # 'fork' (default, production-like): one process group per model step so a
        # timeout can stop descendants. 'inline': call the provider in-process;
        # used by tests and by callers on platforms where fork() is unsafe
        # (macOS with active Objective-C/threaded runtimes). 'inline' forfeits
        # hard timeout interruption of a hung provider call.
        self.step_isolation = step_isolation

    def _setup_workspace(self, run_id: str, task_def: dict[str, Any]) -> Path:
        """Create a clean isolated workspace and populate initial fixtures."""
        ws = self.base_dir / f"run_{run_id}"
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True, exist_ok=True)

        for filename, content in task_def.get("initial_files", {}).items():
            file_path = _workspace_file(ws, filename)
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
            try:
                target = _workspace_file(workspace_dir, rel_path)
            except ValueError as exc:
                return {"status": "error", "message": str(exc)}
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
            try:
                target = _workspace_file(workspace_dir, rel_path)
            except ValueError as exc:
                return {"status": "error", "message": str(exc)}
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

    def _generate_step(self, task_view: dict[str, Any], step: int,
                       history: list[dict[str, Any]], ws: Path, remaining_s: float) -> dict[str, Any]:
        if remaining_s <= 0:
            raise StepTimeoutError("task deadline exceeded")
        if self.step_isolation == "inline":
            return self.provider.generate_step(task_view, step, history, ws)
        # E0 is a single-worker local experiment. Fork is used here so the
        # provider callable stays compatible with test doubles on macOS.
        ctx = multiprocessing.get_context("fork")
        parent, child = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_provider_worker,
                           args=(self.provider, task_view, step, history, ws, child))
        proc.start()
        child.close()
        try:
            if not parent.poll(remaining_s):
                raise StepTimeoutError("model step timed out")
            if not parent.poll():
                raise RuntimeError("model process exited without a result")
            kind, value, calls, call_log = parent.recv()
            proc.join(timeout=1)
            if kind != "ok":
                raise RuntimeError(value)
            if calls is not None:
                self.provider.calls = calls
            if call_log is not None:
                self.provider.call_log = call_log
            return value
        finally:
            parent.close()
            # The provider may have spawned children that outlive its result.
            # They belong to the worker's dedicated session/process group.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                if proc.is_alive():
                    proc.kill()
            proc.join(timeout=1)

    def _reservation_hint(self) -> tuple[int, int]:
        """Per-step reservation caps, overridable by the provider.

        Chain providers make several model calls per step, so the default
        single-call caps would under-reserve. Reported usage above the cap is
        still settled in full (never truncated).
        """
        hint = getattr(self.provider, "reservation_hint", None)
        if callable(hint):
            try:
                value = hint()
                if (isinstance(value, (tuple, list)) and len(value) == 2
                        and all(isinstance(v, int) and v > 0 for v in value)):
                    return int(value[0]), int(value[1])
            except Exception:  # noqa: BLE001 - fall back to defaults
                pass
        return 2000, 1000

    def _run_metadata(self, chain_log: list[dict[str, Any]], *, steps_taken: int) -> dict[str, Any]:
        """Provenance for the run: provider identity, chain records, environment."""
        metadata: dict[str, Any] = {"kernel_steps": steps_taken}
        getter = getattr(self.provider, "metadata", None)
        if callable(getter):
            try:
                provider_meta = getter()
                if isinstance(provider_meta, dict):
                    metadata.update(provider_meta)
            except Exception as exc:  # noqa: BLE001 - provenance must not break a run
                metadata["metadata_error"] = f"{type(exc).__name__}: {exc}"
        provider_mode = getattr(self.provider, "provider_mode", None)
        metadata.setdefault("provider_mode", provider_mode or "fake")
        if chain_log:
            metadata["chain"] = chain_log
            metadata["chain_model_calls"] = sum(int(c.get("model_calls", 0)) for c in chain_log)
            metadata["chain_tool_calls"] = sum(int(c.get("tool_calls", 0)) for c in chain_log)
            metadata["chain_steps"] = sum(int(c.get("chain_steps", 0)) for c in chain_log)
        return metadata

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
        if spec.candidate_id != candidate.candidate_id or spec.task_id != task_def.get("task_id"):
            raise ValueError("RunSpec candidate_id/task_id does not match inputs")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", spec.run_id):
            raise ValueError("run_id must be a simple filename-safe identifier")
        fingerprint_payload = {"candidate_digest": candidate.digest, "task": task_def,
                               "spec": vars(spec), "provider": type(self.provider).__name__,
                               "mode": getattr(self.provider, "mode", None)}
        cache_identity = getattr(self.provider, "cache_identity", None)
        if callable(cache_identity):
            fingerprint_payload["provider_settings"] = cache_identity()
        fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True,
                                                 default=str).encode()).hexdigest()
        if self.journal.is_run_completed(spec.run_id):
            if self.journal.get_run_fingerprint(spec.run_id) != fingerprint:
                raise ValueError("run_id was already used with different or unverifiable inputs")
            cached = self.journal.get_run(spec.run_id)
            if cached is not None:
                return cached

        if spec.run_id in self.budget.interrupted_run_ids:
            result = RunResult(spec.run_id, "crashed", 0.0, "",
                               self.budget.get_run_usage(spec.run_id), "")
            self.journal.record_run_completion(result, candidate.candidate_id,
                                               spec.task_id, fingerprint)
            return result

        # 2. Setup isolated workspace
        ws = self._setup_workspace(spec.run_id, task_def)
        progress = ProgressTracker()
        history: list[dict[str, Any]] = []
        step_events: list[dict[str, Any]] = []
        chain_log: list[dict[str, Any]] = []
        input_cap, output_cap = self._reservation_hint()

        status: RunStatus = "failed"
        stagnant_detected = False
        steps_taken = 0
        deadline = time.monotonic() + spec.timeout_s
        task_view = {key: task_def[key] for key in ("task_id", "instruction", "family", "output_file")
                     if key in task_def}

        try:
            for step in range(1, spec.max_steps + 1):
                steps_taken = step
                # Check timeout
                if time.monotonic() >= deadline:
                    status = "timeout"
                    break

                # Reserve budget for model call
                res_id = None
                try:
                    res_id = self.budget.reserve(input_cap=input_cap, output_cap=output_cap,
                                                 call_type="execution", run_id=spec.run_id,
                                                 api_call_cap=int(getattr(self.provider, "max_model_calls", 1)))
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
                    step_out = self._generate_step(task_view, step, history, ws,
                                                   deadline - time.monotonic())
                    action = step_out.get("action", {})
                    call_usage = step_out.get("usage", {})
                    self.budget.settle(res_id, call_usage)
                except StepTimeoutError:
                    self.budget.settle(res_id, None)
                    status = "timeout"
                    break
                except Exception:
                    # Settle conservatively upon error
                    self.budget.settle(res_id, None)
                    status = "crashed"
                    break

                # Real-chain providers execute tools themselves (through the frozen
                # ToolExecutor) and report the results here. The kernel records them
                # instead of re-executing, so no side effect happens twice.
                chain_info = step_out.get("chain")
                if isinstance(chain_info, dict) and chain_info:
                    chain_log.append(chain_info)
                    self.journal.record_event(
                        EvolutionEvent(
                            run_id=spec.run_id,
                            candidate_id=candidate.candidate_id,
                            task_id=spec.task_id,
                            step=step,
                            event_type="diagnosis",
                            payload={"chain": chain_info},
                        )
                    )
                tool_results = step_out.get("tool_results")
                if isinstance(tool_results, list) and tool_results:
                    for item in tool_results:
                        if not isinstance(item, dict):
                            continue
                        act = {"name": item.get("name", ""),
                               "arguments": item.get("arguments") or {}}
                        obs = {
                            "status": item.get("outcome") or ("ok" if item.get("success") else "error"),
                            "outcome": item.get("outcome") or ("ok" if item.get("success") else "error"),
                            "success": bool(item.get("success")),
                            "tool_reported_success": item.get("tool_reported_success"),
                            "content": str(item.get("result") or item.get("error_message") or ""),
                            "executed_by": "kage_chain",
                        }
                        history.append({"step": step, "action": act, "observation": obs})
                        self.journal.record_event(
                            EvolutionEvent(
                                run_id=spec.run_id,
                                candidate_id=candidate.candidate_id,
                                task_id=spec.task_id,
                                step=step,
                                event_type="action",
                                payload={"action": act, "source": "kage_chain"},
                            )
                        )
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
                        prog_result = progress.observe(act, obs)
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

                # Record the kernel-level step action (intent for the legacy path,
                # completion marker for the chain path).
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

                if isinstance(tool_results, list) and tool_results:
                    if action.get("name") == "finish":
                        break
                    continue

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
                usage=self.budget.get_run_usage(spec.run_id),
                final_state_path=str(ws),
                progress_stagnant=stagnant_detected,
                rollback_count=0,
                metadata=self._run_metadata(chain_log, steps_taken=steps_taken),
            )

            # Record completion in journal
            self.journal.record_run_completion(result, candidate.candidate_id,
                                               spec.task_id, fingerprint)
            return result

        finally:
            if not retain_workspace:
                self._cleanup_workspace(ws)

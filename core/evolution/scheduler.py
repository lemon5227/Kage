"""Idle-time self-evolution: run the E1 skill search when Kage has failures to learn from.

The scheduler is a Heartbeat trigger source. On each heartbeat it may start one
background search run (never more than one at a time) and, when a run finishes,
it records the outcome. It never installs anything: promotion results stay in
the run's report and adoption needs the user's consent (see core/skill_adoption.py).

Conditions for a run (all must hold):
  * ``evolution.auto`` is true (default false: the user opts in);
  * the user has been idle for ``idle_minutes``;
  * at least ``min_new_failures`` task failures were noted since the last run;
  * fewer than ``max_runs_per_day`` runs today and today's reported cost is below
    ``daily_budget_usd`` (each run's own cost ceiling is capped at the remainder).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

ROOT = Path(__file__).resolve().parents[2]

DEFAULTS: dict[str, Any] = {
    "auto": False,
    "idle_minutes": 30,
    "max_runs_per_day": 1,
    "daily_budget_usd": 0.05,
    "min_new_failures": 1,
    "provider": "live",
    "runner": "docker",
    "search_config": "eval/evolution/pilot.json",
    "run_timeout_s": 1800,
}

Launcher = Callable[[Path, str, str, float], Awaitable[dict]]


async def subprocess_launcher(config_path: Path, provider: str, runner: str, timeout_s: float) -> dict:
    """Run ``kage_evolve.py search`` in its own process so it can be killed on timeout."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts/kage_evolve.py"), "search",
        "--config", str(config_path), "--provider", provider, "--runner", runner,
        cwd=str(ROOT), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"returncode": None, "error": f"timeout after {timeout_s}s"}
    return {"returncode": proc.returncode, "stdout": stdout.decode(errors="replace")[-4000:],
            "stderr": stderr.decode(errors="replace")[-4000:]}


class EvolutionScheduler:
    def __init__(self, config: Optional[dict], session_manager: Any, *,
                 workspace_dir: str = "~/.kage",
                 launcher: Launcher = subprocess_launcher,
                 now_fn: Callable[[], float] = time.time) -> None:
        self.config = {**DEFAULTS, **(config or {})}
        self.session = session_manager
        self.launcher = launcher
        self.now_fn = now_fn
        self.base = Path(os.path.expanduser(workspace_dir)) / "evolution"
        self.log_path = self.base / "scheduler.jsonl"
        self.state_path = self.base / "scheduler_state.json"
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ state
    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"pending_failures": []}

    def _save_state(self, state: dict) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _log(self, row: dict) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.now_fn(), **row}, ensure_ascii=False) + "\n")

    def runs(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        rows = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def note_failure(self, job: dict) -> None:
        """Remember a failed/unknown task as material for the next evolution run."""
        state = self._state()
        pending = state.setdefault("pending_failures", [])
        pending.append({"ts": self.now_fn(), "task_id": job.get("task_id"),
                        "run_id": job.get("run_id") or job.get("job_id"), "status": job.get("status")})
        del pending[:-50]
        self._save_state(state)

    # -------------------------------------------------------------- decisions
    def _today_finished(self) -> list[dict]:
        today = datetime.date.fromtimestamp(self.now_fn())
        return [r for r in self.runs() if r.get("event") == "finished"
                and datetime.date.fromtimestamp(float(r.get("ts") or 0)) == today]

    def spent_today(self) -> float:
        return sum(float(r.get("cost_usd") or 0) for r in self._today_finished())

    def should_run(self) -> tuple[bool, str]:
        cfg = self.config
        if not cfg["auto"]:
            return False, "disabled"
        if self._task is not None and not self._task.done():
            return False, "running"
        last = self.session.get_last_user_time() if self.session is not None else None
        if last is not None and self.now_fn() - last < float(cfg["idle_minutes"]) * 60:
            return False, "user_active"
        if len(self._state().get("pending_failures", [])) < int(cfg["min_new_failures"]):
            return False, "no_new_failures"
        if len(self._today_finished()) >= int(cfg["max_runs_per_day"]):
            return False, "daily_run_limit"
        if self.spent_today() >= float(cfg["daily_budget_usd"]):
            return False, "daily_budget"
        return True, ""

    # ---------------------------------------------------------------- running
    def _prepare_config(self, run_id: str) -> Path:
        source = Path(self.config["search_config"])
        if not source.is_absolute():
            source = ROOT / source
        config = json.loads(source.read_text(encoding="utf-8"))
        run_dir = self.base / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        config["output_dir"] = str(run_dir)
        remaining = max(0.0, float(self.config["daily_budget_usd"]) - self.spent_today())
        budget = config.setdefault("budget", {})
        ceiling = budget.get("max_cost_usd")
        budget["max_cost_usd"] = min(float(ceiling), remaining) if ceiling else remaining
        path = run_dir / "search_config.json"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    async def _run(self, run_id: str, failures: list[dict]) -> dict:
        config_path = self._prepare_config(run_id)
        self._log({"event": "started", "run_id": run_id, "failures": failures,
                   "provider": self.config["provider"], "runner": self.config["runner"]})
        try:
            outcome = await self.launcher(config_path, self.config["provider"], self.config["runner"],
                                          float(self.config["run_timeout_s"]))
        except Exception as exc:  # the launcher itself broke; record, never crash Heartbeat
            outcome = {"returncode": None, "error": f"{type(exc).__name__}: {exc}"}
        reports = sorted(config_path.parent.rglob("report.json"))
        report = {}
        if reports:
            try:
                report = json.loads(reports[0].read_text(encoding="utf-8"))
            except ValueError:
                report = {}
        promoted = [c for c in report.get("comparisons", []) if c.get("promoted")]
        row = {
            "event": "finished", "run_id": run_id,
            "returncode": outcome.get("returncode"), "error": outcome.get("error"),
            "stop_reason": report.get("stop_reason"),
            "cost_usd": float(report.get("estimated_cost_usd") or 0),
            "promoted": bool(promoted),
            "active_candidate": report.get("active_candidate") if promoted else None,
            "report_path": str(reports[0]) if reports else None,
        }
        self._log(row)
        return row

    def start(self) -> Optional[str]:
        """Start one background run if allowed; returns its run id."""
        ok, _reason = self.should_run()
        if not ok:
            return None
        state = self._state()
        failures = state.get("pending_failures", [])
        state["pending_failures"] = []
        self._save_state(state)
        run_id = datetime.datetime.fromtimestamp(self.now_fn()).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self._task = asyncio.create_task(self._run(run_id, failures))
        return run_id

    def report_notifications(self) -> list[dict]:
        """One summary of runs finished since the last announcement (failures included).

        When a run promoted a candidate, the notification offers ``adopt_skill`` for the
        most recent such run; accepting is the user's consent (see core/skill_adoption.py).
        """
        from core.proactive import make_notification

        state = self._state()
        since = float(state.get("announced_until") or 0)
        fresh = [r for r in self.runs() if r.get("event") == "finished" and float(r.get("ts") or 0) > since]
        if not fresh:
            return []
        promoted = [r for r in fresh if r.get("promoted")]
        errors = [r for r in fresh if r.get("error") or (r.get("returncode") not in (0, None) and not r.get("promoted"))]
        no_gain = len(fresh) - len(promoted) - len(errors)
        parts = []
        if promoted:
            parts.append(f"{len(promoted)} 次找到了在对比测试中更好的做法")
        if no_gain > 0:
            parts.append(f"{no_gain} 次没有比原来更好")
        if errors:
            parts.append(f"{len(errors)} 次没跑完（环境或预算问题）")
        content = f"你不在的时候我练习了 {len(fresh)} 次：" + "，".join(parts) + "。"
        action = None
        if promoted:
            latest = promoted[-1]
            content += "要启用新学到的技能吗？"
            action = {"type": "adopt_skill", "run_id": latest.get("run_id")}
        note = make_notification(f"evolution:report:{fresh[-1].get('run_id')}", content,
                                 type_="evolution_report", action=action)
        state["announced_until"] = max(float(r.get("ts") or 0) for r in fresh)
        self._save_state(state)
        return [note]

    async def collect(self, now: datetime.datetime) -> list[dict]:
        """Heartbeat source hook: report finished runs, then start a new run when allowed."""
        notes = self.report_notifications()
        self.start()
        return notes

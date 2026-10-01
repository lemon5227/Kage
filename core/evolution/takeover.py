"""Task-level teacher takeover using the existing chain, executor and evaluator.

This trusted experiment coordinator owns the checker. Only the goal and observed
history go to models; expected answers and evaluator cases never enter prompts.
"""
from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path

from core.evolution.completion import completion_summary
from core.evolution.progress import ProgressTracker
from core.evolution.runner import Evaluator


def state_digest(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(workspace)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def tool_history(rows: list[dict]) -> list[dict]:
    return [{"action": {"name": row["name"], "arguments": row["arguments"]},
             "observation": {"success": row["success"], "outcome": row["outcome"],
                             "content": row["result"], "actor": row.get("actor")}} for row in rows]


class TeacherTakeoverProvider:
    """One bounded student attempt, then at most one bounded teacher attempt."""
    def __init__(self, student, teacher, task_def: dict):
        self.student, self.teacher, self.task_def = student, teacher, task_def
        self.max_model_calls = student.max_model_calls + teacher.max_model_calls
        self.provider_mode = "task-level-takeover"
        self.calls = 0
        self.call_log = []

    def reservation_hint(self):
        a, b = self.student.reservation_hint(), self.teacher.reservation_hint()
        return a[0] + b[0], a[1] + b[1]

    def cache_identity(self):
        return {"student": self.student.cache_identity(), "teacher": self.teacher.cache_identity(),
                "takeover_policy": "failed-external-check-v1", "task": self.task_def}

    def metadata(self):
        return {"provider_mode": self.provider_mode, "student": self.student.metadata(),
                "teacher": self.teacher.metadata(), "model_call_guard": self.max_model_calls}

    @staticmethod
    def _attempt(chain, task, step, history, workspace):
        try:
            return chain.generate_step(task, step, history, workspace)
        except Exception as exc:
            # Unknown usage is conservatively reserved, never reported as free.
            return {"tool_results": [], "usage": {"api_calls": chain.max_model_calls},
                    "chain": {"stop_reason": "call_error", "model_errors": [f"{type(exc).__name__}: {exc}"],
                              "usage_unknown": True, "model_calls": chain.max_model_calls}}

    def generate_step(self, task_def, step, history, workspace_dir):
        if task_def.get("task_id") != self.task_def.get("task_id"):
            raise ValueError("takeover checker task does not match execution task")
        task_def = {k: task_def[k] for k in ("task_id", "instruction", "family", "output_file") if k in task_def}
        self.calls += 1
        ws = Path(workspace_dir)
        initial_digest = state_digest(ws)
        local = self._attempt(self.student, task_def, step, history, ws)
        local_rows = [dict(row, actor="student") for row in local["tool_results"]]
        progress = ProgressTracker()
        stagnant = False
        for item in tool_history(local_rows):
            stagnant |= progress.observe(item["action"], item["observation"])["stagnant"]
        local_score = Evaluator.score(self.task_def, ws)
        local_check = completion_summary(local_score, local["chain"]["stop_reason"], stagnant=stagnant)
        takeover = {"triggered": local_score < 1, "student_check": local_check,
                    "initial_state_digest": initial_digest, "failure_state_digest": state_digest(ws),
                    "continued_same_workspace": True, "student_chain": local["chain"],
                    "student_usage": local["usage"]}
        rows, usage, final_chain = local_rows, dict(local["usage"]), local["chain"]
        if local_score < 1:
            snapshot = ws.parent / (ws.name + ".student-state")
            if snapshot.exists():
                shutil.rmtree(snapshot)
            shutil.copytree(ws, snapshot)
            takeover["failure_state_ref"] = str(snapshot.resolve())
            # Checker verdict is exposed; hidden expected output/cases are not.
            observed_history = history + tool_history(local_rows) + [{"observation": {
                "actor": "external_checker", "completion": local_check,
                "message": "The student's attempt did not pass. Reobserve current files, correct the result, and save it."}}]
            remote = self._attempt(self.teacher, task_def, step, observed_history, ws)
            rows += [dict(row, actor="teacher") for row in remote["tool_results"]]
            remote_score = Evaluator.score(self.task_def, ws)
            takeover.update(teacher_check=completion_summary(remote_score, remote["chain"]["stop_reason"]),
                            teacher_chain=remote["chain"], teacher_usage=remote["usage"], final_state_digest=state_digest(ws))
            # If either provider lacks token usage, preserve unknown spend for
            # conservative settlement of the total reservation.
            keys = {"api_calls"} if any("input_tokens" not in x or "output_tokens" not in x
                       for x in [usage, remote["usage"]]) else {"input_tokens", "output_tokens", "api_calls"}
            usage = {key: usage.get(key, 0) + remote["usage"].get(key, 0) for key in keys}
            final_chain = remote["chain"]
        info = {**final_chain, "takeover": takeover, "tool_calls": len(rows),
                "model_calls": usage["api_calls"], "chain_steps": local["chain"].get("chain_steps", 0) +
                    (takeover.get("teacher_chain", {}).get("chain_steps", 0)),
                "actor": "teacher" if takeover["triggered"] else "student"}
        self.call_log.append({"task_id": task_def["task_id"], "step": step, "takeover": takeover["triggered"]})
        return {"action": {"name": "finish", "reason": f'agent chain stopped: {info["stop_reason"]}'},
                "tool_results": rows, "usage": usage, "chain": info}

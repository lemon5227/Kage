"""A local retry control bounded by the same total model-call and loop-step budget."""
from core.evolution.runner import Evaluator
from core.evolution.takeover import TeacherTakeoverProvider, tool_history


class LocalRetryProvider:
    provider_mode = "local-budget-matched-retries"

    def __init__(self, factory, task_def, max_model_calls=6, max_steps=5):
        self.factory, self.task_def = factory, task_def
        self.max_model_calls, self.max_steps = max_model_calls, max_steps
        self.calls, self.call_log = 0, []

    def reservation_hint(self):
        return 8000, 2000

    def cache_identity(self):
        return {"policy": "three-local-attempts-v1", "max_calls": self.max_model_calls,
                "max_steps": self.max_steps, "task": self.task_def}

    def metadata(self):
        return {"provider_mode": self.provider_mode, "max_model_calls": self.max_model_calls,
                "max_total_loop_steps": self.max_steps}

    def generate_step(self, task_def, step, history, workspace_dir):
        if task_def.get("task_id") != self.task_def.get("task_id"):
            raise ValueError("retry checker task mismatch")
        task_def = {k: task_def[k] for k in ("task_id", "instruction", "family", "output_file") if k in task_def}
        attempts, rows, usage, steps = [], [], {"api_calls": 0, "input_tokens": 0, "output_tokens": 0}, 0
        unknown = False
        for attempt in range(3):
            remaining = self.max_model_calls - usage["api_calls"]
            remaining_steps = self.max_steps - steps
            if remaining <= 0 or remaining_steps <= 0:
                break
            chain = self.factory(min(2, remaining), min(2, remaining_steps))
            out = TeacherTakeoverProvider._attempt(chain, task_def, step, history + tool_history(rows), workspace_dir)
            steps += max(1, out["chain"].get("chain_steps", 0))
            rows.extend(dict(row, actor="student", retry=attempt) for row in out["tool_results"])
            for key in usage:
                usage[key] += out["usage"].get(key, 0)
            unknown |= "input_tokens" not in out["usage"] or "output_tokens" not in out["usage"]
            score = Evaluator.score(self.task_def, workspace_dir)
            attempts.append({"attempt": attempt, "chain": out["chain"], "usage": out["usage"], "score": score})
            if score >= 1:
                break
        if unknown:
            usage = {"api_calls": usage["api_calls"]}
        self.calls += 1
        self.call_log.append({"task_id": task_def["task_id"], "attempts": len(attempts)})
        info = {"model_calls": usage["api_calls"], "chain_steps": steps, "tool_calls": len(rows),
                "attempts": attempts, "stop_reason": attempts[-1]["chain"]["stop_reason"] if attempts else "call_limit"}
        return {"action": {"name": "finish", "reason": "local retries stopped"},
                "chain": info, "tool_results": rows, "usage": usage}

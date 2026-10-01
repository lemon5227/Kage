"""Local retry controls share a call/step ceiling and continue actual changed state."""
from core.evolution.agent_provider import KageChainProvider
from core.evolution.retries import LocalRetryProvider
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import SequenceModel, call


def test_retry_keeps_partial_file_and_stops_when_external_check_passes(tmp_path):
    task = {"task_id": "retry", "instruction": "Double 7 into out.json", "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": 14}}
    models = iter([
        SequenceModel([call("write_file", path="out.json", content="7"), ModelResponse(text="Done")]),
        SequenceModel([call("read_file", path="out.json"), call("write_file", path="out.json", content="14")]),
    ])
    def factory(call_cap, step_cap):
        chain = KageChainProvider(next(models), max_model_calls=call_cap)
        chain.agentic_loop_cls = type("RetryLoop", (chain.agentic_loop_cls,), {"MAX_STEPS": step_cap})
        return chain
    result = LocalRetryProvider(factory, task).generate_step({"task_id": "retry", "instruction": task["instruction"]}, 1, [], tmp_path)
    assert (tmp_path / "out.json").read_text() == "14"
    assert result["usage"]["api_calls"] == 4
    assert len(result["chain"]["attempts"]) == 2
    assert [r["name"] for r in result["tool_results"]] == ["write_file", "read_file", "write_file"]


def test_retries_cannot_multiply_total_step_or_call_budget(tmp_path):
    (tmp_path / "input.json").write_text("7")
    task = {"task_id": "cap", "instruction": "Read input.json and write out.json", "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": 14}}
    def factory(call_cap, step_cap):
        chain = KageChainProvider(SequenceModel([call("read_file", path="input.json")] * call_cap), max_model_calls=call_cap)
        chain.agentic_loop_cls = type("RetryLoop", (chain.agentic_loop_cls,), {"MAX_STEPS": step_cap})
        return chain
    result = LocalRetryProvider(factory, task).generate_step({"task_id": "cap", "instruction": task["instruction"]}, 1, [], tmp_path)
    assert result["usage"]["api_calls"] == 5
    assert result["chain"]["chain_steps"] == 5
    assert len(result["tool_results"]) == 5
    assert not (tmp_path / "out.json").exists()


def test_direct_retry_call_keeps_hidden_checks_out_of_student_input(tmp_path):
    task = {"task_id": "private", "instruction": "Write out.json", "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": 987654}}
    seen = []
    class Chain:
        max_model_calls = 1
        def generate_step(self, view, *args):
            seen.append(view)
            return {"tool_results": [], "usage": {"api_calls": 1, "input_tokens": 1, "output_tokens": 1}, "chain": {"chain_steps": 1, "stop_reason": "model_returned"}}
    LocalRetryProvider(lambda *args: Chain(), task).generate_step(task, 1, [], tmp_path)
    assert seen and all(view == {"task_id": "private", "instruction": "Write out.json"} for view in seen)

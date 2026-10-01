"""External checks, not model prose or tool success, decide task completion."""
from pathlib import Path
from core.evolution.runner import Evaluator
from core.evolution.contracts import RunSpec
from test_evolution_agent_chain import _runner, _candidate, _chain_provider
from test_agentic_loop_multistep import SequenceModel, call


def test_code_checker_executes_boundary_cases_and_rejects_wrong_function(tmp_path):
    task = {"scoring_criteria": {"type": "python_function", "file": "helper.py", "function": "clamp", "cases": [
        {"args": [-2, 0, 3], "expected": 0}, {"args": [2, 0, 3], "expected": 2},
        {"args": [4, 0, 3], "expected": 3}, {"args": [1, 3, 0], "raises": "ValueError"}]}}
    path = tmp_path / "helper.py"
    path.write_text("def clamp(value, low, high):\n    return low\n")
    assert Evaluator.score(task, tmp_path) == 0
    path.write_text("def clamp(value, low, high):\n    if low > high: raise ValueError()\n    return max(low, min(high, value))\n")
    assert Evaluator.score(task, tmp_path) == 1
    path.write_text("while True: pass\n")
    assert Evaluator.score(task, tmp_path) == 0


def test_stalled_reads_are_logged_as_no_progress_with_independent_failed_check(tmp_path):
    provider = _chain_provider(SequenceModel([call("read_file", path="input.json")] * 5))
    runner, _ = _runner(tmp_path, provider, isolation="inline")
    candidate = _candidate(tmp_path)
    task = {"task_id": "stalled", "instruction": "Read input.json and save out.json.",
            "initial_files": {"input.json": "[1]"},
            "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": [2]}}
    result = runner.run(candidate, task, RunSpec("stalled", candidate.candidate_id, "stalled"))
    assert result.status == "failed" and result.score == 0
    assert result.metadata["completion"]["status"] == "no_progress"
    assert result.metadata["completion"]["stop_reason"] == "step_limit"
    assert result.metadata["completion"]["check_passed"] is False


def test_verified_file_can_pass_even_when_final_summary_hit_call_cap(tmp_path):
    provider = _chain_provider(SequenceModel([call("write_file", path="out.json", content="[2]")]), max_model_calls=1)
    runner, _ = _runner(tmp_path, provider, isolation="inline")
    candidate = _candidate(tmp_path)
    task = {"task_id": "cap_ok", "instruction": "Write out.json then verify it.",
            "scoring_criteria": {"type": "json_exact_match", "file": "out.json", "expected": [2]}}
    result = runner.run(candidate, task, RunSpec("cap_ok", candidate.candidate_id, "cap_ok"))
    assert result.status == "passed" and result.score == 1
    assert result.metadata["completion"] == {"status": "completed", "stop_reason": "call_limit", "check_passed": True}
    assert result.usage["api_calls"] == 1

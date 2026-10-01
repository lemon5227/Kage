"""Stopping a model is distinct from completing its task; preserve executed work."""
import asyncio

from core.evolution.agent_provider import KageChainProvider
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import call, make_loop, SequenceModel


def test_model_call_cap_preserves_file_and_trace_without_claiming_completion(tmp_path):
    model = SequenceModel([call("write_file", path="out.txt", content="partial")])
    provider = KageChainProvider(model, max_model_calls=1)
    result = provider.generate_step({"task_id": "cap", "instruction": "Write out.txt, then verify it."}, 1, [], tmp_path)
    assert (tmp_path / "out.txt").read_text() == "partial"
    assert result["chain"]["stop_reason"] == "call_limit"
    assert len(result["tool_results"]) == 1
    assert result["usage"]["api_calls"] == 1
    assert result["action"]["reason"] == "agent chain stopped: call_limit"


def test_steps_exhausted_does_not_claim_task_completion(tmp_path):
    (tmp_path / "input.txt").write_text("7")
    loop, _, _ = make_loop(tmp_path, [call("read_file", path="input.txt")] * 5)
    result = asyncio.run(loop.run("Read input.txt and write doubled value into out.txt."))
    assert result.stop_reason == "step_limit"
    assert len(result.tool_calls_executed) == 5
    assert not (tmp_path / "out.txt").exists()


def test_normal_model_reply_is_only_a_return_not_a_verified_success(tmp_path):
    provider = KageChainProvider(SequenceModel([ModelResponse(text="Done.")]))
    result = provider.generate_step({"task_id": "empty", "instruction": "Summarize the data."}, 1, [], tmp_path)
    assert result["chain"]["stop_reason"] == "model_returned"
    assert result["action"]["reason"] == "agent chain stopped: model_returned"

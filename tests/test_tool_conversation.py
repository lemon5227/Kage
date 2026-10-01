"""Tool evidence must be a paired conversation, not invented assistant prose."""
import asyncio
import json

from core.anthropic_provider import _convert_messages
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import call, make_loop


def test_model_receives_call_arguments_and_matching_tool_result(tmp_path):
    (tmp_path / "sales.csv").write_text("amount\n7\n")
    goal = "Read sales.csv and write totals.json."
    loop, model, _ = make_loop(tmp_path, [
        call("read_file", path="sales.csv"),
        call("write_file", path="totals.json", content='{"total":7}'),
        ModelResponse(text="written"),
    ])
    asyncio.run(loop.run(goal))
    messages = model.messages[1]
    assistant = next(m for m in messages if m.get("tool_calls"))
    tool = next(m for m in messages if m["role"] == "tool")
    request = assistant["tool_calls"][0]
    assert json.loads(request["function"]["arguments"]) == {"path": "sales.csv"}
    assert tool["tool_call_id"] == request["id"]
    assert "amount\\n7" in tool["content"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert sum(m.get("content") == goal for m in messages) == 1
    assert (tmp_path / "totals.json").read_text() == '{"total":7}'


def test_budget_drops_whole_tool_exchange(tmp_path):
    loop, _, _ = make_loop(tmp_path, [])
    history = [{"role": "user", "content": "goal"}]
    for i in range(6):
        history.extend([
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path":"input"}'}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 500},
        ])
    messages, _ = loop.prompt.build("goal", history)
    # Applies both the route history window and token trimming.
    messages = loop.prompt._enforce_budget(messages, 150)
    calls = {c["id"] for m in messages for c in m.get("tool_calls", [])}
    results = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    assert calls == results
    assert messages[1] == {"role": "user", "content": "goal"}


def test_anthropic_keeps_tool_use_and_result_in_native_blocks():
    _, messages = _convert_messages([
        {"role": "user", "content": "Read input."},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
         "function": {"name": "read_file", "arguments": '{"path":"input"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "actual contents"},
    ])
    assert messages[1]["content"] == [{"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "input"}}]
    assert messages[2]["content"] == [{"type": "tool_result", "tool_use_id": "c1", "content": "actual contents"}]


def test_token_estimate_includes_tool_arguments(tmp_path):
    loop, _, _ = make_loop(tmp_path, [])
    empty = [{"role": "assistant", "content": ""}]
    large = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "write_file", "arguments": "x" * 4000}}]}]
    assert loop.prompt.count_tokens(large) > loop.prompt.count_tokens(empty) + 500

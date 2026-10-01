"""A successful intermediate tool must not terminate a compound task."""
import asyncio
import json

from core.agentic_loop import AgenticLoop
from core.evolution.agent_provider import (
    ExperimentIdentityStore, HistorySession, build_workspace_registry,
)
from core.model_provider import ModelResponse
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolDefinition


class SequenceModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def generate(self, messages, **kwargs):
        self.messages.append(messages)
        return next(self.responses)


def call(name, **arguments):
    return ModelResponse(text="", tool_calls=[{"name": name, "arguments": arguments}])


def make_loop(workspace, responses):
    registry = build_workspace_registry(workspace)
    model = SequenceModel(responses)
    builder = PromptBuilder(ExperimentIdentityStore(), None, registry,
                            memory_cfg={"recall_enabled": False})
    loop = AgenticLoop(model, ToolExecutor(registry, str(workspace)), builder, HistorySession())
    return loop, model, registry


def test_command_reads_writes_and_checks_actual_file(tmp_path):
    (tmp_path / "input.txt").write_text("7")
    loop, model, _ = make_loop(tmp_path, [
        call("read_file", path="input.txt"),
        call("write_file", path="output.txt", content="14"),
        call("read_file", path="output.txt"),
        ModelResponse(text="已写入并读回。"),
    ])
    result = asyncio.run(loop.run("读取 input.txt 文件，把数值翻倍写到 output.txt，再读回核验。"))
    assert (tmp_path / "output.txt").read_text() == "14"
    assert [tc["name"] for tc in result.tool_calls_executed] == ["read_file", "write_file", "read_file"]
    assert len(model.messages) == 4


def test_single_system_command_keeps_fast_reply(tmp_path):
    loop, model, registry = make_loop(tmp_path, [call("system_control", target="brightness", action="up")])
    state = {"brightness": 10}
    def control(target, action):
        state[target] += 1
        return json.dumps({"success": True})
    registry.register(ToolDefinition("system_control", "Change a test setting", {
        "type": "object", "properties": {"target": {"type": "string"}, "action": {"type": "string"}},
        "required": ["target", "action"]}, control))
    result = asyncio.run(loop.run("帮我把亮度调高一点"))
    assert state["brightness"] == 11
    assert len(model.messages) == 1 and result.steps == 1


def test_system_action_does_not_end_compound_request(tmp_path):
    loop, model, registry = make_loop(tmp_path, [
        call("system_control", target="brightness", action="up"),
        call("write_file", path="receipt.txt", content="brightness changed"),
        ModelResponse(text="已记录。"),
    ])
    registry.register(ToolDefinition("system_control", "Change a test setting", {
        "type": "object", "properties": {"target": {"type": "string"}, "action": {"type": "string"}},
        "required": ["target", "action"]}, lambda **kwargs: json.dumps({"success": True})))
    asyncio.run(loop.run("把亮度调高，然后把操作记录写入 receipt.txt 文件。"))
    assert (tmp_path / "receipt.txt").read_text() == "brightness changed"
    assert len(model.messages) == 3

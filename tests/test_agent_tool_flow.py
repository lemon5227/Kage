"""Vertical checks that a model can see and use tool capabilities."""

import asyncio
import json

from core.agentic_loop import AgenticLoop
from core.model_provider import ModelResponse
from core.prompt_builder import PromptBuilder
from core.session_state import SessionState
from core.tool_executor import ToolExecutor
from core.tool_registry import create_default_registry
from core.tool_registry import ToolDefinition
from core.tools import web_ops
from core.tools.skill_ops import skills_save_local


class _Identity:
    def load_soul(self):
        return ""

    def load_user(self):
        return ""


class _SearchModel:
    def __init__(self):
        self.calls = 0
        self.visible_tools = set()

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.calls += 1
        self.visible_tools = {tool["function"]["name"] for tool in (tools or [])}
        if self.calls == 1 and "search" in self.visible_tools:
            return ModelResponse(text="", tool_calls=[{"name": "search", "arguments": {
                "query": "小猫", "source": "youtube", "max_results": 3}}])
        return ModelResponse(text="搜索完成")


class _TimeModel:
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(text="", tool_calls=[{"name": "get_time", "arguments": {}}])
        return ModelResponse(text="查询完成")


def test_search_reaches_backend_through_real_agent_path(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(web_ops, "_search_provider_youtube", lambda q, sort, limit: (
        seen.append((q, sort, limit)) or '{"success": true, "results": []}'))
    registry = create_default_registry()
    prompt = PromptBuilder(_Identity(), None, registry, memory_cfg={"recall_enabled": False}, prune_tools=True)
    model = _SearchModel()
    executor = ToolExecutor(registry, workspace_dir=str(tmp_path))
    loop = AgenticLoop(model, executor, prompt, SessionState())

    result = asyncio.run(loop.run("搜索小猫视频"))

    assert "search" in model.visible_tools
    assert seen == [("小猫", "relevance", 3)]
    assert any(row["name"] == "search" and row["success"] for row in result.tool_calls_executed)


def test_tool_executor_reports_structured_failure_to_agent(tmp_path):
    executor = ToolExecutor(create_default_registry(), workspace_dir=str(tmp_path))
    result = asyncio.run(executor.execute("skills_save_local", {
        "name": "../../escape", "description": "invalid", "target_dir": str(tmp_path)}))
    assert json.loads(result.result)["success"] is False
    assert result.success is False
    assert result.error_type == "InvalidArgument"


def test_repeat_request_autosave_uses_registered_tool_even_when_pruned(tmp_path):
    registry = create_default_registry()
    original = registry._tools["skills_save_local"]

    def save_to_test_dir(name, description, body="", target_dir="~/.kage/skills", overwrite=False):
        return skills_save_local(name, description, body, target_dir=str(tmp_path / "skills"), overwrite=overwrite)

    registry.register(ToolDefinition(original.name, original.description,
                                     original.parameters, save_to_test_dir))
    prompt = PromptBuilder(_Identity(), None, registry, memory_cfg={"recall_enabled": False}, prune_tools=True)
    executor = ToolExecutor(registry, workspace_dir=str(tmp_path))
    history = [
        {"role": "user", "content": "查询时间"}, {"role": "assistant", "content": "之前结果"},
        {"role": "user", "content": "查询时间"}, {"role": "assistant", "content": "之前结果"},
    ]
    loop = AgenticLoop(_TimeModel(), executor, prompt, SessionState(history=history))

    result = asyncio.run(loop.run("查询时间"))

    assert any(row["name"] == "skills_save_local" and row["success"]
               for row in result.tool_calls_executed), (result.tool_calls_executed, result.final_text, result.steps)
    assert list((tmp_path / "skills").glob("auto-*.md"))


def test_saved_skill_is_findable_and_readable_through_registered_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    executor = ToolExecutor(create_default_registry(), workspace_dir=str(tmp_path))
    saved = asyncio.run(executor.execute("skills_save_local", {
        "name": "video-research", "description": "检索视频资料", "body": "## Steps\nSearch YouTube.",
    }))
    assert saved.success

    found = asyncio.run(executor.execute("find_skills", {"query": "video-research"}))
    assert found.success
    assert any(item["name"] == "video-research" for item in json.loads(found.result)["skills"])

    loaded = asyncio.run(executor.execute("skills_read", {"skill_name": "video-research"}))
    assert loaded.success
    assert "Search YouTube." in json.loads(loaded.result)["content"]

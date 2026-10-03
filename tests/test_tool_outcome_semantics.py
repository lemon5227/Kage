"""Tool outcomes must be classified, rendered and propagated without lying.

Two real defects motivate this file:

  * ``ToolExecutor`` marked every handler return as ``success=True``, so a handler
    answering ``{"success": false}`` (bad arguments, refused preconditions) was reported
    to the Agent as a success — the Agent could believe a skill was saved when it was
    not;
  * the first fix collapsed every ``success: false`` payload into "tool failed", which
    also mislabels *domain-negative* answers such as ``NoResults``:
    those are legitimate answers, not execution failures, and should not push the Agent
    into retry/fallback behaviour.

The model is a contract: ``success`` means "the tool answered trustworthily",
``outcome`` preserves state semantics, and ``tool_reported_success`` preserves the payload's own verdict.
Identical saves are unchanged/successful; conflicting saves are not_applied/unsuccessful.
"""

from __future__ import annotations

import asyncio
import json
import tempfile

import pytest

from core.agentic_loop import AgenticLoop
from core.model_provider import ModelResponse
from core.prompt_builder import PromptBuilder
from core.session_state import SessionState
from core.tool_executor import ToolExecutor, classify_tool_payload, render_history_line
from core.tool_registry import ToolDefinition, ToolRegistry, create_default_registry


class _Identity:
    def load_soul(self) -> str:
        return ""

    def load_user(self) -> str:
        return ""


class _OneShotModel:
    """Calls one tool on the first step, then answers."""

    def __init__(self, call: dict) -> None:
        self.call = call
        self.steps = 0
        self.observed: list[str] = []

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.steps += 1
        if self.steps == 1:
            return ModelResponse(text="", tool_calls=[self.call])
        self.observed = [str(message.get("content") or "") for message in messages]
        return ModelResponse(text="finished")


def _registry_with(name: str, handler) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name=name, description="d",
                                     parameters={"type": "object", "properties": {}},
                                     handler=handler))
    return registry


# ---------------------------------------------------------------------------
# Payload classification table
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payload,expected", [
    ({"success": True, "value": 1}, ("ok", True, None, None)),
    ({"success": False, "error": "NoResults", "message": "未找到结果"},
     ("no_results", False, "NoResults", "未找到结果")),
    ({"success": False, "error": "NotFound"}, ("no_results", False, "NotFound", "")),
    ({"success": False, "error": "AlreadyExists"}, ("rejected", False, "AlreadyExists", "")),
    ({"success": False, "error": "InvalidArgument", "message": "参数无效"},
     ("rejected", False, "InvalidArgument", "参数无效")),
    ({"success": False}, ("rejected", False, "ToolFailed", "")),
    # unknown failure code: distinguishable from a fixable rejection
    ({"success": False, "error": "WeirdInternalCrash", "message": "boom"},
     ("tool_error", False, "WeirdInternalCrash", "boom")),
    ("a plain string", ("unknown_payload", None, None, None)),
    (42, ("unknown_payload", None, None, None)),
])
def test_payload_classification(payload, expected):
    assert classify_tool_payload(payload) == expected


def test_render_history_line_phrasing():
    assert render_history_line("t", True, "body") == "[Tool: t] body"
    assert render_history_line("t", True, "body", "NoResults", "未找到结果", "no_results") \
        == "[Tool: t] （无结果）body"
    rejected = render_history_line("t", False, "", "InvalidArgument", "参数无效", "rejected")
    assert "调用被拒绝" in rejected and "尝试替代方案" not in rejected
    errored = render_history_line("t", False, "", "RuntimeError", "boom", "error")
    assert "尝试替代方案" in errored
    unknown = render_history_line("t", False, "", "WeirdInternalCrash", "boom", "tool_error")
    assert "未分类的失败码" in unknown and "调用被拒绝" not in unknown


def test_browser_error_rendering_preserves_uncertain_action_and_malformed_fallback():
    payload={"success":False,"error":"BrowserTimeout","message":"click timed out",
             "outcome":"tool_error","action_applied":None,"observation":{"observation_id":"new"}}
    line=render_history_line("browser_act",False,json.dumps(payload),"BrowserTimeout","click timed out","tool_error")
    assert json.loads(line.split('] ',1)[1])==payload
    assert 'BrowserTimeout' in render_history_line("browser_act",False,'{broken',"BrowserTimeout","click timed out","tool_error")
    assert '调用被拒绝' in render_history_line("ordinary",False,json.dumps(payload),"InvalidArgument","bad","rejected")


# ---------------------------------------------------------------------------
# Through the real executor
# ---------------------------------------------------------------------------
def test_executor_adopts_the_payload_verdict():
    def refuses(**kwargs) -> str:
        return json.dumps({"success": False, "error": "InvalidArgument", "message": "参数无效"})

    registry = _registry_with("refuses", refuses)
    with tempfile.TemporaryDirectory() as tmp:
        executor = ToolExecutor(registry, workspace_dir=tmp)
        result = asyncio.run(executor.execute("refuses", {}))
    assert result.success is False
    assert result.outcome == "rejected"
    assert result.error_type == "InvalidArgument"
    assert result.tool_reported_success is False


def test_executor_treats_no_results_as_an_answer_not_a_failure():
    def empty(**kwargs) -> str:
        return json.dumps({"success": False, "error": "NoResults", "message": "未找到结果"})

    registry = _registry_with("empty", empty)
    with tempfile.TemporaryDirectory() as tmp:
        executor = ToolExecutor(registry, workspace_dir=tmp)
        result = asyncio.run(executor.execute("empty", {}))
    assert result.success is True, "found-nothing must not be reported as a tool failure"
    assert result.outcome == "no_results"
    assert result.error_type == "NoResults"


def test_executor_reports_exceptions_as_errors():
    def boom(**kwargs) -> str:
        raise RuntimeError("kaboom")

    registry = _registry_with("boom", boom)
    with tempfile.TemporaryDirectory() as tmp:
        executor = ToolExecutor(registry, workspace_dir=tmp)
        result = asyncio.run(executor.execute("boom", {}))
    assert result.success is False
    assert result.outcome == "error"
    assert result.error_type == "RuntimeError"


def test_real_skill_save_reports_success_then_already_exists(tmp_path):
    executor = ToolExecutor(create_default_registry(), workspace_dir=str(tmp_path))
    args = {"name": "demo-skill", "description": "d", "body": "b", "target_dir": str(tmp_path)}

    saved = asyncio.run(executor.execute("skills_save_local", dict(args)))
    assert saved.success is True and saved.outcome == "ok"

    again = asyncio.run(executor.execute("skills_save_local", {**args, "body": "different"}))
    assert again.outcome == "not_applied" and again.error_type == "AlreadyExists"
    assert again.success is False, "a refused write must not look like a completed write"
    assert (tmp_path / "demo-skill.md").read_text().endswith("b\n")


# ---------------------------------------------------------------------------
# End to end: what the model actually reads
# ---------------------------------------------------------------------------
def _run_one_tool(call: dict, registry: ToolRegistry, tmp_path) -> list[str]:
    prompt = PromptBuilder(_Identity(), None, registry,
                           memory_cfg={"recall_enabled": False}, prune_tools=False)
    session = SessionState()
    model = _OneShotModel(call)
    loop = AgenticLoop(model, ToolExecutor(registry, workspace_dir=str(tmp_path)),
                       prompt, session)
    asyncio.run(loop.run("执行这个调用"))
    return model.observed


def test_model_sees_a_rejection_as_an_error(tmp_path):
    def refuses(**kwargs) -> str:
        return json.dumps({"success": False, "error": "InvalidArgument", "message": "参数无效"})

    history = _run_one_tool({"name": "refuses", "arguments": {}},
                            _registry_with("refuses", refuses), tmp_path)
    assert any("[Tool Error: refuses] InvalidArgument" in line for line in history), history
    assert any("调用被拒绝" in line for line in history), history


def test_model_does_not_see_no_results_as_an_error(tmp_path):
    def empty(**kwargs) -> str:
        return json.dumps({"success": False, "error": "NoResults", "message": "未找到结果"})

    history = _run_one_tool({"name": "empty", "arguments": {}},
                            _registry_with("empty", empty), tmp_path)
    assert any("（无结果）" in line for line in history), history
    assert not any("[Tool Error: empty]" in line for line in history), history


def test_failed_tool_call_is_visible_in_executed_calls(tmp_path):
    """Astra's regression: a structured failure must reach the Agent, not look like success."""
    executor = ToolExecutor(create_default_registry(), workspace_dir=str(tmp_path))
    result = asyncio.run(executor.execute("skills_save_local",
                                          {"name": "../../escape", "description": "x",
                                           "target_dir": str(tmp_path)}))
    assert result.success is False
    assert result.outcome == "rejected"
    assert result.error_type == "InvalidArgument"
    assert "调用被拒绝" in result.history_line()

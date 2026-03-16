"""Tests for ToolExecutor — multi-format parsing, security, logging."""

import json
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.tool_executor import ToolExecutor, ToolResult
from core.tool_registry import ToolRegistry, ToolDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path)


@pytest.fixture
def mock_registry():
    """Create a mock ToolRegistry with basic tools."""
    registry = ToolRegistry()
    
    # Register some test tools
    registry.register(ToolDefinition(
        name="get_time",
        description="获取当前时间",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "2024-01-01 12:00",
        safety_level="SAFE",
    ))
    
    registry.register(ToolDefinition(
        name="open_app",
        description="打开应用",
        parameters={"type": "object", "properties": {"app_name": {"type": "string"}}},
        handler=lambda app_name="": f"已打开 {app_name}",
        safety_level="SAFE",
    ))
    
    registry.register(ToolDefinition(
        name="run_cmd",
        description="执行命令",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        handler=lambda command="": f"执行: {command}",
        safety_level="DANGEROUS",
    ))
    
    registry.register(ToolDefinition(
        name="custom_skill",
        description="自定义技能",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "custom result",
        safety_level="SAFE",
    ))
    
    return registry


@pytest.fixture
def executor(mock_registry, workspace):
    return ToolExecutor(tool_registry=mock_registry, workspace_dir=workspace)


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParseToolCalls:
    def test_empty_input(self, executor):
        assert executor.parse_tool_calls("") == []
        assert executor.parse_tool_calls("   ") == []
        assert executor.parse_tool_calls(None) == []

    def test_action_format(self, executor):
        text = '>>>ACTION: open_app app_name="Safari"'
        results = executor.parse_tool_calls(text)
        assert len(results) == 1
        assert results[0]["name"] == "open_app"
        assert results[0]["arguments"]["app_name"] == "Safari"

    def test_action_format_multiple(self, executor):
        text = '>>>ACTION: get_time\n>>>ACTION: open_app app_name="Chrome"'
        results = executor.parse_tool_calls(text)
        assert len(results) == 2

    def test_action_format_single_quotes(self, executor):
        text = ">>>ACTION: open_app app_name='Firefox'"
        results = executor.parse_tool_calls(text)
        assert len(results) == 1
        assert results[0]["arguments"]["app_name"] == "Firefox"

    def test_pythonic_format(self, executor):
        text = 'open_app(app_name="Safari")'
        results = executor.parse_tool_calls(text)
        assert len(results) == 1
        assert results[0]["name"] == "open_app"
        assert results[0]["arguments"]["app_name"] == "Safari"

    def test_pythonic_unknown_function_ignored(self, executor):
        text = 'unknown_func(arg="val")'
        results = executor.parse_tool_calls(text)
        assert results == []

    def test_no_match_returns_empty(self, executor):
        text = "just some random text with no tool calls"
        results = executor.parse_tool_calls(text)
        assert results == []


# ---------------------------------------------------------------------------
# Security classification
# ---------------------------------------------------------------------------

class TestSecurityLevel:
    def test_safe_tools(self, executor):
        assert executor.get_security_level("get_time") == "SAFE"
        assert executor.get_security_level("open_app") == "SAFE"
        assert executor.get_security_level("custom_skill") == "SAFE"

    def test_dangerous_tools(self, executor):
        assert executor.get_security_level("run_cmd") == "DANGEROUS"

    def test_unknown_tool_defaults_safe(self, executor):
        assert executor.get_security_level("some_new_tool") == "SAFE"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class TestExecute:
    def test_successful_execution(self, executor):
        result = asyncio.get_event_loop().run_until_complete(
            executor.execute("get_time", {})
        )
        assert result.success is True
        assert result.name == "get_time"
        assert result.elapsed_ms >= 0
        assert result.error_type is None

    def test_unknown_tool_returns_error(self, executor):
        result = asyncio.get_event_loop().run_until_complete(
            executor.execute("nonexistent_tool", {})
        )
        assert result.success is False
        assert result.error_type == "UnknownTool"
        assert "未知工具" in result.error_message

    def test_dangerous_tool_with_confirmation(self, executor):
        confirm = AsyncMock(return_value=True)
        result = asyncio.get_event_loop().run_until_complete(
            executor.execute("run_cmd", {"command": "ls"}, require_confirmation=confirm)
        )
        confirm.assert_called_once_with("run_cmd", {"command": "ls"})
        assert result.success is True

    def test_dangerous_tool_denied(self, executor):
        confirm = AsyncMock(return_value=False)
        result = asyncio.get_event_loop().run_until_complete(
            executor.execute("run_cmd", {"command": "rm -rf /"}, require_confirmation=confirm)
        )
        assert result.success is False
        assert result.error_type == "UserDenied"

    def test_safe_tool_skips_confirmation(self, executor):
        confirm = AsyncMock(return_value=True)
        result = asyncio.get_event_loop().run_until_complete(
            executor.execute("get_time", {}, require_confirmation=confirm)
        )
        confirm.assert_not_called()
        assert result.success is True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging:
    def test_tool_log_written(self, executor, workspace):
        asyncio.get_event_loop().run_until_complete(
            executor.execute("get_time", {})
        )
        log_file = os.path.join(workspace, "tool_log.jsonl")
        assert os.path.exists(log_file)
        with open(log_file, "r") as f:
            record = json.loads(f.readline())
        assert record["name"] == "get_time"
        assert "timestamp" in record
        assert "elapsed_ms" in record
        assert record["success"] is True

    def test_audit_log_for_dangerous(self, executor, workspace):
        asyncio.get_event_loop().run_until_complete(
            executor.execute("run_cmd", {"command": "ls"})
        )
        audit_file = os.path.join(workspace, "audit.log")
        assert os.path.exists(audit_file)
        with open(audit_file, "r") as f:
            content = f.read()
        assert "DANGEROUS" in content
        assert "run_cmd" in content

    def test_no_audit_log_for_safe(self, executor, workspace):
        asyncio.get_event_loop().run_until_complete(
            executor.execute("get_time", {})
        )
        audit_file = os.path.join(workspace, "audit.log")
        assert not os.path.exists(audit_file)


# ---------------------------------------------------------------------------
# ToolResult dataclass
# ---------------------------------------------------------------------------

class TestToolResult:
    def test_success_result(self):
        r = ToolResult(name="test", success=True, result="ok", elapsed_ms=10.5)
        assert r.error_type is None
        assert r.error_message is None

    def test_failure_result(self):
        r = ToolResult(
            name="test", success=False, result="",
            error_type="RuntimeError", error_message="fail",
            elapsed_ms=5.0,
        )
        assert r.error_type == "RuntimeError"
        assert r.elapsed_ms >= 0

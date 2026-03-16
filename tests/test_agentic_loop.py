"""Tests for AgenticLoop — multi-step tool execution loop."""

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from core.agentic_loop import (
    AgenticLoop, LoopResult, detect_repetition, DEFAULT_REPLY, VALID_EMOTIONS,
)
from core.model_provider import ModelResponse
from core.tool_executor import ToolResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model():
    m = MagicMock()
    m.generate.return_value = ModelResponse(text="你好！", tool_calls=[])
    return m


@pytest.fixture
def tool_executor():
    te = MagicMock()
    te.parse_tool_calls.return_value = []
    te.execute = AsyncMock(return_value=ToolResult(
        name="test", success=True, result="ok", elapsed_ms=10,
    ))
    return te


@pytest.fixture
def prompt_builder():
    pb = MagicMock()
    # 新接口：返回 (messages, tool_schemas) tuple
    pb.build.return_value = (
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ],
        [{"type": "function", "function": {"name": "test", "description": "test", "parameters": {}}}],
    )
    return pb


@pytest.fixture
def session():
    sm = MagicMock()
    sm.get_history.return_value = []
    return sm


@pytest.fixture
def loop(model, tool_executor, prompt_builder, session):
    return AgenticLoop(model, tool_executor, prompt_builder, session)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string(self, loop):
        result = run(loop.run(""))
        assert result.final_text == DEFAULT_REPLY
        assert result.emotion == "neutral"
        assert result.steps == 0

    def test_whitespace_only(self, loop):
        result = run(loop.run("   \n\t  "))
        assert result.final_text == DEFAULT_REPLY
        assert result.steps == 0

    def test_none_input(self, loop):
        result = run(loop.run(None))
        assert result.final_text == DEFAULT_REPLY


# ---------------------------------------------------------------------------
# Pure text response (terminates after 1 step)
# ---------------------------------------------------------------------------

class TestPureTextResponse:
    def test_terminates_on_pure_text(self, loop, model):
        model.generate.return_value = ModelResponse(text="天气很好", tool_calls=[])
        result = run(loop.run("今天天气怎么样"))
        assert result.final_text == "天气很好"
        assert result.steps == 1
        assert result.tool_calls_executed == []

    def test_emotion_neutral_no_tools(self, loop, model):
        model.generate.return_value = ModelResponse(text="hi", tool_calls=[])
        result = run(loop.run("hello"))
        assert result.emotion == "neutral"


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

class TestToolExecution:
    def test_executes_tool_and_returns(self, loop, model, tool_executor):
        # First call: model returns tool call
        # Second call: model returns pure text
        model.generate.side_effect = [
            ModelResponse(text="", tool_calls=[{"name": "get_time", "arguments": {}}]),
            ModelResponse(text="现在是下午3点", tool_calls=[]),
        ]
        tool_executor.execute = AsyncMock(return_value=ToolResult(
            name="get_time", success=True, result="15:00", elapsed_ms=5,
        ))

        result = run(loop.run("几点了"))
        assert result.steps == 2
        assert len(result.tool_calls_executed) == 1
        assert result.tool_calls_executed[0]["name"] == "get_time"

    def test_tool_failure_feeds_back_error(self, loop, model, tool_executor):
        model.generate.side_effect = [
            ModelResponse(text="", tool_calls=[{"name": "open_app", "arguments": {"app_name": "X"}}]),
            ModelResponse(text="找不到应用 X", tool_calls=[]),
        ]
        tool_executor.execute = AsyncMock(return_value=ToolResult(
            name="open_app", success=False, result="",
            error_type="RuntimeError", error_message="not found",
            elapsed_ms=5,
        ))

        result = run(loop.run("打开X"))
        assert result.steps == 2
        assert result.emotion == "sad"

    def test_emotion_happy_on_success(self, loop, model, tool_executor):
        model.generate.side_effect = [
            ModelResponse(text="", tool_calls=[{"name": "open_app", "arguments": {"app_name": "Safari"}}]),
            ModelResponse(text="已打开", tool_calls=[]),
        ]
        tool_executor.execute = AsyncMock(return_value=ToolResult(
            name="open_app", success=True, result="已打开 Safari ✨", elapsed_ms=100,
        ))

        result = run(loop.run("打开Safari"))
        assert result.emotion == "happy"


# ---------------------------------------------------------------------------
# Max steps
# ---------------------------------------------------------------------------

class TestMaxSteps:
    def test_stops_at_max_steps(self, loop, model, tool_executor):
        # Model always returns tool calls
        model.generate.return_value = ModelResponse(
            text="", tool_calls=[{"name": "get_time", "arguments": {}}],
        )
        tool_executor.execute = AsyncMock(return_value=ToolResult(
            name="get_time", success=True, result="15:00", elapsed_ms=5,
        ))

        result = run(loop.run("loop forever"))
        assert result.steps == 5
        assert len(result.tool_calls_executed) == 5


# ---------------------------------------------------------------------------
# Repetition detection
# ---------------------------------------------------------------------------

class TestRepetitionDetection:
    def test_no_repetition(self):
        assert detect_repetition("hello world this is unique text") is False

    def test_short_text(self):
        assert detect_repetition("short") is False

    def test_repeated_pattern(self):
        text = "PM me now " * 5
        assert detect_repetition(text) is True

    def test_threshold_exact(self):
        # "abcdefghij" repeated exactly 3 times
        text = "abcdefghij" * 3
        assert detect_repetition(text) is True

    def test_below_threshold(self):
        text = "abcdefghij" * 2 + "something else entirely"
        assert detect_repetition(text) is False

    def test_loop_stops_on_repetition(self, loop, model, tool_executor):
        repeated = "重复内容啊" * 10  # 50 chars, "重复内容啊重复内容啊重" appears 3+ times
        model.generate.return_value = ModelResponse(text=repeated, tool_calls=[])
        tool_executor.parse_tool_calls.return_value = []

        result = run(loop.run("test"))
        assert result.steps == 1
        # Should have truncated the repetition
        assert len(result.final_text) <= len(repeated)


# ---------------------------------------------------------------------------
# Emotion validity
# ---------------------------------------------------------------------------

class TestEmotionValidity:
    def test_all_emotions_valid(self, loop, model):
        model.generate.return_value = ModelResponse(text="ok", tool_calls=[])
        result = run(loop.run("hi"))
        assert result.emotion in VALID_EMOTIONS

    def test_thinking_during_tool_execution(self, loop, model, tool_executor):
        """During tool execution, emotion should be 'thinking'."""
        # This is implicit — the loop sets emotion to "thinking" internally
        # We verify the final emotion is correct based on outcome
        model.generate.side_effect = [
            ModelResponse(text="", tool_calls=[{"name": "get_time", "arguments": {}}]),
            ModelResponse(text="done", tool_calls=[]),
        ]
        tool_executor.execute = AsyncMock(return_value=ToolResult(
            name="get_time", success=True, result="15:00", elapsed_ms=5,
        ))
        result = run(loop.run("time"))
        assert result.emotion == "happy"


# ---------------------------------------------------------------------------
# LoopResult
# ---------------------------------------------------------------------------

class TestLoopResult:
    def test_defaults(self):
        r = LoopResult(final_text="hi")
        assert r.emotion == "neutral"
        assert r.tool_calls_executed == []
        assert r.steps == 0

    def test_with_data(self):
        r = LoopResult(
            final_text="done",
            emotion="happy",
            tool_calls_executed=[{"name": "test"}],
            steps=3,
        )
        assert r.steps == 3


# ---------------------------------------------------------------------------
# Command inference confidence
# ---------------------------------------------------------------------------

class TestCommandInferenceConfidence:
    def test_high_confidence_imperative_command(self):
        call, conf = AgenticLoop._infer_command_tool_call_scored("帮我把亮度调高一点")
        assert isinstance(call, dict)
        assert call["name"] == "system_control"
        assert conf >= 0.9

    def test_low_confidence_question_does_not_trigger(self):
        call, conf = AgenticLoop._infer_command_tool_call_scored("什么是蓝牙？")
        assert conf < 0.5
        assert AgenticLoop._infer_command_tool_call("什么是蓝牙？") is None


class TestParallelizableToolCalls:
    def test_parallelizable_read_only_tools(self):
        calls = [
            {"name": "web_fetch", "arguments": {"url": "https://example.com"}},
            {"name": "search", "arguments": {"query": "kage"}},
        ]
        assert AgenticLoop._can_parallelize_tool_calls(calls) is True

    def test_non_parallelizable_when_side_effect_tool_present(self):
        calls = [
            {"name": "web_fetch", "arguments": {"url": "https://example.com"}},
            {"name": "skills_read", "arguments": {"skill_name": "x"}},
        ]
        assert AgenticLoop._can_parallelize_tool_calls(calls) is False


class TestParallelMetrics:
    def test_parallel_metrics_reports_saved_time(self):
        rows = [
            {"elapsed_ms": 120.0},
            {"elapsed_ms": 80.0},
        ]
        m = AgenticLoop._parallel_metrics(rows, wall_ms=130.0)
        assert m["sum_ms"] == 200.0
        assert m["saved_ms"] > 60.0
        assert m["speedup"] > 1.0

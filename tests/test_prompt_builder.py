"""Tests for PromptBuilder — dynamic prompt assembly with dual-channel tools."""

import datetime
from unittest.mock import MagicMock

import pytest

from core.prompt_builder import PromptBuilder
from core.tool_registry import ToolRegistry, ToolDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def identity():
    store = MagicMock()
    store.load_soul.return_value = "我是 Kage，傲娇但靠谱的终端精灵"
    store.load_user.return_value = "用户: 小明\n时区: Asia/Shanghai"
    return store


@pytest.fixture
def memory():
    mem = MagicMock()
    mem.recall.return_value = [
        {"content": "用户喜欢用 Chrome", "importance": 3},
    ]
    return mem


@pytest.fixture
def tool_registry():
    """Create a mock ToolRegistry with test tools."""
    registry = ToolRegistry()
    
    registry.register(ToolDefinition(
        name="open_app",
        description="打开应用。当用户想打开某个应用时使用。",
        parameters={"type": "object", "properties": {"app_name": {"type": "string"}}},
        handler=lambda app_name="": f"已打开 {app_name}",
        safety_level="SAFE",
    ))
    
    registry.register(ToolDefinition(
        name="get_time",
        description="获取当前时间。当用户询问时间时使用。",
        parameters={"type": "object", "properties": {}},
        handler=lambda: "12:00",
        safety_level="SAFE",
    ))
    
    registry.register(ToolDefinition(
        name="web_search",
        description="搜索网页信息。当用户想搜索资料时使用。",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=lambda query="": f"搜索: {query}",
        safety_level="SAFE",
    ))
    
    return registry


@pytest.fixture
def builder(identity, memory, tool_registry):
    return PromptBuilder(identity, memory, tool_registry, max_context_tokens=4096)


# ---------------------------------------------------------------------------
# Build tests
# ---------------------------------------------------------------------------

class TestBuild:
    def test_returns_messages_and_schemas(self, builder):
        msgs, schemas = builder.build("你好", history=[])
        assert isinstance(msgs, list)
        assert isinstance(schemas, list)
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "你好"

    def test_system_prompt_contains_soul(self, builder):
        msgs, _ = builder.build("hi", history=[])
        system = msgs[0]["content"]
        assert "Kage" in system

    def test_system_prompt_contains_user_info(self, builder):
        msgs, _ = builder.build("hi", history=[])
        system = msgs[0]["content"]
        assert "小明" in system

    def test_system_prompt_contains_time(self, builder):
        msgs, _ = builder.build("hi", history=[])
        system = msgs[0]["content"]
        today = datetime.date.today().isoformat()
        assert today in system

    def test_system_prompt_contains_memory(self, builder):
        msgs, _ = builder.build("你好", history=[])
        system = msgs[0]["content"]
        assert "Chrome" in system

    def test_system_prompt_contains_behavior_rule(self, builder):
        msgs, _ = builder.build("hi", history=[])
        system = msgs[0]["content"]
        assert "先尝试自己解决" in system

    def test_system_prompt_contains_tool_descriptions(self, builder):
        """双通道：系统提示词包含工具描述文本"""
        msgs, _ = builder.build("hi", history=[])
        system = msgs[0]["content"]
        assert "open_app" in system
        assert "get_time" in system
        assert "web_search" in system

    def test_returns_tool_schemas(self, builder):
        """双通道：返回工具 JSON Schema"""
        _, schemas = builder.build("hi", history=[])
        assert len(schemas) == 3
        # 验证 Schema 格式
        for schema in schemas:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]

    def test_includes_history(self, builder):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
        ]
        msgs, _ = builder.build("second", history=history)
        # system + 2 history + user input = 4
        assert len(msgs) == 4
        assert msgs[1]["content"] == "first"
        assert msgs[2]["content"] == "reply"

    def test_memory_recall_failure_graceful(self, builder, memory):
        memory.recall.side_effect = Exception("DB error")
        msgs, schemas = builder.build("hi", history=[])
        # Should still return valid messages
        assert len(msgs) >= 2
        assert len(schemas) >= 0


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

class TestCountTokens:
    def test_basic_count(self, builder):
        msgs = [{"role": "user", "content": "hello world"}]
        tokens = builder.count_tokens(msgs)
        assert tokens >= 1

    def test_empty_messages(self, builder):
        assert builder.count_tokens([]) >= 1

    def test_longer_content_more_tokens(self, builder):
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "a" * 300}]
        assert builder.count_tokens(long) > builder.count_tokens(short)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

class TestBudgetEnforcement:
    def test_no_trimming_when_under_budget(self, builder):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = builder._enforce_budget(msgs, budget=1000)
        assert len(result) == 2

    def test_trims_oldest_history(self, builder):
        msgs = [
            {"role": "system", "content": "x" * 300},
            {"role": "user", "content": "old1"},
            {"role": "assistant", "content": "old_reply1"},
            {"role": "user", "content": "old2"},
            {"role": "assistant", "content": "old_reply2"},
            {"role": "user", "content": "recent1"},
            {"role": "assistant", "content": "recent_reply1"},
            {"role": "user", "content": "current"},
        ]
        result = builder._enforce_budget(msgs, budget=50)
        # Should keep system + last 3 history + user input = 5
        assert len(result) == 5
        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "current"

    def test_preserves_minimum_context(self, builder):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "user", "content": "current"},
        ]
        result = builder._enforce_budget(msgs, budget=1)
        # Can't trim below 5 messages
        assert len(result) == 5

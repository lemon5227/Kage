import asyncio
import json


class _DummyPrompt:
    def __init__(self, tool_defs):
        self._tool_defs = tool_defs
        self.last_route = "info"

    def build(self, user_input, history, current_emotion="neutral"):
        self.last_route = "info"
        return [
            {"role": "system", "content": "s"},
            {"role": "user", "content": user_input},
        ], self._tool_defs


class _DummySession:
    def get_history(self):
        return []


class _DummyModel:
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        from core.model_provider import ModelResponse

        self.calls += 1
        # Planner fails to output tool calls both times.
        if tools:
            return ModelResponse(text="", tool_calls=[])
        # Responder called after deterministic smart_search fallback.
        return ModelResponse(text="尼斯明天多云。", tool_calls=[])


class _ToolResult:
    def __init__(self, name, success, result, error_type=None, error_message=None, elapsed_ms=1.0):
        self.name = name
        self.success = success
        self.result = result
        self.error_type = error_type
        self.error_message = error_message
        self.elapsed_ms = elapsed_ms


class _DummyExecutor:
    def __init__(self):
        self.calls = []

    def parse_tool_calls(self, text):
        return []

    async def execute(self, name, arguments):
        self.calls.append(name)
        if name == "smart_search":
            return _ToolResult(name, True, '{"success": true, "results": [{"title": "抖音热词", "url": "https://www.douyin.com/abc", "content": "x"}, {"title": "曹操说最新一期 - YouTube", "url": "https://www.youtube.com/watch?v=1", "content": "y"}]}')
        return _ToolResult(name, True, "ok")


def test_info_route_deterministic_search_fallback_when_model_no_tool_calls():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {"name": "smart_search", "description": "", "parameters": {"type": "object"}},
        },
        {
            "type": "function",
            "function": {"name": "web_fetch", "description": "", "parameters": {"type": "object"}},
        },
    ]

    ex = _DummyExecutor()
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=ex,
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("帮我查一下明天尼斯天气"))
    assert res.final_text
    assert any(n in ex.calls for n in ("smart_search", "web_fetch"))


def test_video_reply_prefers_youtube_domain_when_available():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {"name": "smart_search", "description": "", "parameters": {"type": "object"}},
        },
        {
            "type": "function",
            "function": {"name": "web_fetch", "description": "", "parameters": {"type": "object"}},
        },
    ]

    ex = _DummyExecutor()
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=ex,
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("帮我找曹操说最新视频"))
    assert "youtube.com" in res.final_text.lower()


def test_weather_failed_tools_returns_clean_fallback_text():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {"name": "web_fetch", "description": "", "parameters": {"type": "object"}},
        }
    ]

    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=_DummyExecutor(),
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )

    text = loop._respond_from_tools_with_model(
        "帮我查一下明天尼斯天气",
        [
            {
                "name": "web_fetch",
                "arguments": {"url": "https://wttr.in/Nice?format=j1"},
                "success": False,
                "result": '{"success": false, "error": "HTTPError", "status_code": 404}',
                "error_type": "HTTPError",
                "error_message": "Not Found",
            }
        ],
    )

    assert any(k in text for k in ("天气", "度", "明天"))
    assert "404" not in text


def test_weather_web_fetch_fallback_mentions_weather():
    from core.agentic_loop import AgenticLoop

    payload = json.dumps(
        {
            "success": True,
            "content": json.dumps({"current_condition": [{"temp_C": "21"}]}, ensure_ascii=False),
        },
        ensure_ascii=False,
    )

    text = AgenticLoop._fallback_text_from_tools(
        [
            {
                "name": "web_fetch",
                "success": True,
                "result": payload,
            }
        ],
        user_input="帮我查一下明天尼斯天气",
    )

    assert any(k in text for k in ("天气", "度", "明天"))

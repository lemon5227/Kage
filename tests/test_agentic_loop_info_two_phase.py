import asyncio


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
        self.calls = []

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        from core.model_provider import ModelResponse

        self.calls.append({"tools": bool(tools), "max_tokens": max_tokens})

        # Planner phase: request a search tool call.
        if tools:
            return ModelResponse(
                text="",
                tool_calls=[
                    {
                        "name": "smart_search",
                        "arguments": {"query": "尼斯 明天天气", "max_results": 3, "strategy": "auto"},
                    }
                ],
            )

        # Responder phase: generate final answer from tool output.
        return ModelResponse(text="尼斯明天多云，气温约12到17度。", tool_calls=[])


class _ToolResult:
    def __init__(self, name, success, result, error_type=None, error_message=None, elapsed_ms=1.0):
        self.name = name
        self.success = success
        self.result = result
        self.error_type = error_type
        self.error_message = error_message
        self.elapsed_ms = elapsed_ms


class _DummyExecutor:
    def parse_tool_calls(self, text):
        return []

    async def execute(self, name, arguments):
        if name == "smart_search":
            return _ToolResult(
                name,
                True,
                '{"success": true, "results": [{"title": "Nice weather", "content": "Tomorrow cloudy 12-17C"}]}',
                elapsed_ms=5.0,
            )
        return _ToolResult(name, True, "ok", elapsed_ms=1.0)


def test_info_route_uses_two_phase_planner_responder():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {"name": "smart_search", "description": "", "parameters": {"type": "object"}},
        }
    ]

    model = _DummyModel()
    loop = AgenticLoop(
        model_provider=model,
        tool_executor=_DummyExecutor(),
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("帮我查一下明天尼斯天气"))

    assert "尼斯" in res.final_text
    # Expect 2 model calls: planner (with tools) + responder (without tools)
    assert len(model.calls) == 2
    assert model.calls[0]["tools"] is True
    assert model.calls[1]["tools"] is False

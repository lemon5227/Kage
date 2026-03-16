import asyncio


class _DummyPrompt:
    def __init__(self, tool_defs):
        self._tool_defs = tool_defs

    def build(self, user_input, history, current_emotion="neutral"):
        return [{"role": "system", "content": "s"}, {"role": "user", "content": user_input}], self._tool_defs


class _DummySession:
    def __init__(self, hist):
        self._hist = hist

    def get_history(self):
        return list(self._hist)


class _DummyModel:
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        from core.model_provider import ModelResponse

        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                text="",
                tool_calls=[{"name": "fs_search", "arguments": {"query": "a"}}],
            )
        return ModelResponse(text="done", tool_calls=[])


class _ToolResult:
    def __init__(self, name, success, result, error_type=None, error_message=None):
        self.name = name
        self.success = success
        self.result = result
        self.error_type = error_type
        self.error_message = error_message


class _DummyExecutor:
    def __init__(self):
        self.calls = []

    def parse_tool_calls(self, text):
        return []

    async def execute(self, name, arguments):
        self.calls.append(name)
        if name == "skills_save_local":
            return _ToolResult(name, True, "ok")
        return _ToolResult(name, True, "ok")


def test_autosave_after_repeat_requests():
    from core.agentic_loop import AgenticLoop

    # history contains 2 prior identical user requests
    hist = [
        {"role": "user", "content": "帮我找文件"},
        {"role": "assistant", "content": "x"},
        {"role": "user", "content": "帮我找文件"},
        {"role": "assistant", "content": "y"},
    ]
    session = _DummySession(hist)
    ex = _DummyExecutor()

    tool_defs = [
        {"type": "function", "function": {"name": "fs_search", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_save_local", "description": "", "parameters": {"type": "object"}}},
    ]
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=ex,
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=session,
    )

    res = asyncio.run(loop.run("帮我找文件"))
    assert res.final_text == "done"
    assert "skills_save_local" in ex.calls

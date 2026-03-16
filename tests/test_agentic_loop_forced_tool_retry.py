import asyncio


class _DummyPrompt:
    def __init__(self, tool_defs):
        self._tool_defs = tool_defs
        self.inputs = []

    def build(self, user_input, history, current_emotion="neutral"):
        self.inputs.append(user_input)
        return [{"role": "system", "content": "s"}, {"role": "user", "content": user_input}], self._tool_defs


class _DummySession:
    def get_history(self):
        return []


class _DummyModel:
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        from core.model_provider import ModelResponse

        self.calls += 1
        # First call: model "chats" and doesn't call tools.
        if self.calls == 1:
            return ModelResponse(text="我可以帮你整理文件。", tool_calls=[])
        # Second call: returns a tool call.
        return ModelResponse(
            text="",
            tool_calls=[{"name": "fs_apply", "arguments": {"ops": [{"op": "move", "src": "~/a", "dest_dir": "~/b"}]}}],
        )


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
        return _ToolResult(name, True, "ok")


def test_forced_tool_retry_on_file_intent():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {"name": "fs_apply", "description": "", "parameters": {"type": "object"}},
        }
    ]
    prompt = _DummyPrompt(tool_defs)
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=_DummyExecutor(),
        prompt_builder=prompt,
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("帮我整理一下文件"))
    assert res.tool_calls_executed
    # Ensure we did retry with forced instruction.
    assert len(prompt.inputs) >= 2
    assert "你必须调用工具" in prompt.inputs[1]
    assert "优先选择" in prompt.inputs[1]
    assert "fs_apply" in prompt.inputs[1]

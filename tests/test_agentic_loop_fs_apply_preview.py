import asyncio


class _DummyPrompt:
    def __init__(self, tool_defs):
        self._tool_defs = tool_defs

    def build(self, user_input, history, current_emotion="neutral"):
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
        if self.calls == 1:
            return ModelResponse(
                text="",
                tool_calls=[
                    {
                        "name": "fs_apply",
                        "arguments": {
                            "ops": [
                                {"op": "move", "src": "/tmp/a", "dest_dir": "/tmp/b"},
                            ]
                        },
                    }
                ],
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
        if name == "fs_preview":
            return _ToolResult(name, True, "preview")
        if name == "fs_apply":
            return _ToolResult(name, True, "applied")
        return _ToolResult(name, True, "ok")


def test_agentic_loop_previews_before_fs_apply():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {"name": "fs_apply", "description": "", "parameters": {"type": "object"}},
        }
    ]
    ex = _DummyExecutor()
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=ex,
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("organize"))
    assert res.final_text == "done"
    assert ex.calls[:2] == ["fs_preview", "fs_apply"]

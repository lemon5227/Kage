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
        if self.calls == 1:
            return ModelResponse(text="", tool_calls=[{"name": "skills_find_remote", "arguments": {"query": "x"}}])
        if self.calls == 2:
            # Even after skill loaded, model still chats
            return ModelResponse(text="我知道了。", tool_calls=[])
        if self.calls == 3:
            # After follow-skill forced prompt, still no tool
            return ModelResponse(text="嗯嗯。", tool_calls=[])
        # After primitive fallback prompt, return a primitive tool call
        return ModelResponse(text="", tool_calls=[{"name": "fs_search", "arguments": {"query": "report"}}])


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
        import json

        self.calls.append(name)
        if name == "skills_find_remote":
            payload = {
                "results": [
                    {"repo": "vercel-labs/skills", "skill": "find-skills", "url": "https://skills.sh/vercel-labs/skills/find-skills"}
                ]
            }
            return _ToolResult(name, True, json.dumps(payload, ensure_ascii=False))
        if name == "web_fetch":
            return _ToolResult(name, True, "---\nname: find-skills\ndescription: discover\n---\n")
        if name == "skills_install":
            return _ToolResult(name, True, "{\"success\": true}")
        if name == "skills_read":
            return _ToolResult(name, True, '{"name":"find-skills","content":"no-op"}')
        if name == "fs_search":
            return _ToolResult(name, True, '{"success": true, "results": []}')
        return _ToolResult(name, True, "ok")


def test_primitive_fallback_after_skill_stalls():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {"type": "function", "function": {"name": "skills_find_remote", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_install", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_read", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "web_fetch", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "fs_search", "description": "", "parameters": {"type": "object"}}},
    ]
    prompt = _DummyPrompt(tool_defs)
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=_DummyExecutor(),
        prompt_builder=prompt,
        session_manager=_DummySession(),
    )
    res = asyncio.run(loop.run("帮我找文件"))
    assert any(tc["name"] == "fs_search" for tc in res.tool_calls_executed)
    assert any("忽略技能" in s for s in prompt.inputs)

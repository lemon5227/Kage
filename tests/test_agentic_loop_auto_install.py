import asyncio
import json


class _DummyPrompt:
    def __init__(self, tool_defs):
        self._tool_defs = tool_defs

    def build(self, user_input, history, current_emotion="neutral"):
        # messages are not important for this unit test
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
                tool_calls=[{"name": "skills_find_remote", "arguments": {"query": "x", "max_results": 5}}],
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
        self.calls.append((name, arguments))
        if name == "skills_find_remote":
            payload = {
                "results": [
                    {
                        "repo": "vercel-labs/skills",
                        "skill": "find-skills",
                        "ref": "vercel-labs/skills@find-skills",
                        "url": "https://skills.sh/vercel-labs/skills/find-skills",
                        "install_cmd": "...",
                    }
                ]
            }
            return _ToolResult(name, True, json.dumps(payload, ensure_ascii=False))
        if name == "skills_install":
            return _ToolResult(name, True, json.dumps({"success": True}, ensure_ascii=False))
        if name == "skills_read":
            return _ToolResult(name, True, json.dumps({"name": "find-skills", "content": "..."}, ensure_ascii=False))
        return _ToolResult(name, True, "ok")


def test_agentic_loop_auto_installs_after_remote_find():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {
            "type": "function",
            "function": {
                "name": "skills_find_remote",
                "description": "",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]

    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=_DummyExecutor(),
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("need skill"))
    assert res.final_text == "done"
    names = [x["name"] for x in res.tool_calls_executed]
    assert "skills_find_remote" in names
    assert "skills_install" in names
    assert "skills_read" in names

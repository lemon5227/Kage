import asyncio
import json


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
        # 1) Ask to find skills
        if self.calls == 1:
            return ModelResponse(text="", tool_calls=[{"name": "skills_find_remote", "arguments": {"query": "x"}}])
        # 2) After skill loaded, model may still try to chat; we expect forced follow-skill call to happen.
        if self.calls == 2:
            return ModelResponse(text="我知道了。", tool_calls=[])
        # 3) Forced follow-skill call
        return ModelResponse(text="", tool_calls=[{"name": "fs_apply", "arguments": {"ops": [{"op": "move", "src": "~/a", "dest_dir": "~/b"}]}}])


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
        if name == "skills_find_remote":
            payload = {
                "results": [
                    {
                        "repo": "vercel-labs/skills",
                        "skill": "find-skills",
                        "url": "https://skills.sh/vercel-labs/skills/find-skills",
                    },
                    {
                        "repo": "vercel-labs/agent-skills",
                        "skill": "web-design-guidelines",
                        "url": "https://skills.sh/vercel-labs/agent-skills/web-design-guidelines",
                    },
                ]
            }
            return _ToolResult(name, True, json.dumps(payload, ensure_ascii=False))
        if name == "web_fetch":
            url = str((arguments or {}).get("url") or "")
            if "web-design-guidelines" in url:
                return _ToolResult(name, True, "---\nname: web-design-guidelines\ndescription: ui ux accessibility\n---\n")
            return _ToolResult(name, True, "---\nname: find-skills\ndescription: discover and install skills\n---\n")
        if name == "skills_install":
            return _ToolResult(name, True, json.dumps({"success": True}, ensure_ascii=False))
        if name == "skills_read":
            payload = {
                "name": "find-skills",
                "title": "Find Skills",
                "description": "desc",
                "content": "Step 1: do X\nStep 2: do Y",
            }
            return _ToolResult(name, True, json.dumps(payload, ensure_ascii=False))
        if name in ("fs_preview", "fs_apply"):
            return _ToolResult(name, True, "ok")
        return _ToolResult(name, True, "ok")


def test_skill_guidance_forces_next_step_tool_call():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {"type": "function", "function": {"name": "skills_find_remote", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_install", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_read", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "fs_apply", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "fs_preview", "description": "", "parameters": {"type": "object"}}},
    ]

    prompt = _DummyPrompt(tool_defs)
    ex = _DummyExecutor()
    loop = AgenticLoop(
        model_provider=_DummyModel(),
        tool_executor=ex,
        prompt_builder=prompt,
        session_manager=_DummySession(),
    )

    res = asyncio.run(loop.run("整理一下文件"))
    assert any(tc["name"] == "skills_read" for tc in res.tool_calls_executed)
    assert any(tc["name"] == "fs_apply" for tc in res.tool_calls_executed)
    # Ensure we injected a follow-skill forced prompt at least once.
    assert any("技能指引" in s for s in prompt.inputs)

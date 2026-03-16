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
        # 1) Find skills
        if self.calls == 1:
            return ModelResponse(text="", tool_calls=[{"name": "skills_find_remote", "arguments": {"query": "x"}}])
        # 2) Model fails to progress even after first skill loaded.
        if self.calls == 2:
            return ModelResponse(text="我知道了。", tool_calls=[])
        # 3) After fallback skill loaded, produce an actionable tool call.
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
        self.installs = []

    def parse_tool_calls(self, text):
        return []

    async def execute(self, name, arguments):
        self.calls.append(name)
        if name == "skills_find_remote":
            payload = {
                "results": [
                    {"repo": "vercel-labs/skills", "skill": "find-skills", "url": "https://skills.sh/vercel-labs/skills/find-skills"},
                    {"repo": "vercel-labs/agent-skills", "skill": "organize-files", "url": "https://skills.sh/vercel-labs/agent-skills/organize-files"},
                ]
            }
            return _ToolResult(name, True, json.dumps(payload, ensure_ascii=False))
        if name == "web_fetch":
            url = str((arguments or {}).get("url") or "")
            if "organize-files" in url:
                return _ToolResult(name, True, "---\nname: organize-files\ndescription: organize files and folders using fs_apply\n---\n")
            return _ToolResult(name, True, "---\nname: find-skills\ndescription: discover and install skills\n---\n")
        if name == "skills_install":
            self.installs.append(arguments)
            return _ToolResult(name, True, json.dumps({"success": True}, ensure_ascii=False))
        if name == "skills_read":
            skill = str((arguments or {}).get("skill_name") or "")
            if skill == "organize-files":
                payload = {"name": "organize-files", "content": "use fs_apply"}
            else:
                payload = {"name": "find-skills", "content": "no-op"}
            return _ToolResult(name, True, json.dumps(payload, ensure_ascii=False))
        if name in ("fs_preview", "fs_apply"):
            return _ToolResult(name, True, "ok")
        return _ToolResult(name, True, "ok")


def test_skill_fallback_installs_backup_and_progresses():
    from core.agentic_loop import AgenticLoop

    tool_defs = [
        {"type": "function", "function": {"name": "skills_find_remote", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_install", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "skills_read", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "web_fetch", "description": "", "parameters": {"type": "object"}}},
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
    assert any(tc["name"] == "fs_apply" for tc in res.tool_calls_executed)
    # Ensure we installed at least one skill; fallback may install a second.
    assert ex.installs

import asyncio


def test_normalize_fs_apply_move_keys(tmp_path):
    from core.tool_registry import ToolRegistry, ToolDefinition
    from core.tool_executor import ToolExecutor

    seen = {}

    def _handler(ops):
        seen["ops"] = ops
        return "ok"

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="fs_apply",
            description="apply",
            parameters={"type": "object", "properties": {"ops": {"type": "array"}}, "required": ["ops"]},
            handler=_handler,
            safety_level="SAFE",
        )
    )
    ex = ToolExecutor(tool_registry=reg, workspace_dir=str(tmp_path / "ws"))

    args = {"ops": [{"op": "mv", "from": "~/a.txt", "dest": "~/Archive"}]}
    res = asyncio.run(ex.execute("fs_apply", args))
    assert res.success is True
    assert seen["ops"][0] == {"op": "move", "src": "~/a.txt", "dest_dir": "~/Archive"}


def test_normalize_fs_apply_delete_synonym_triggers_confirmation(tmp_path):
    from core.tool_registry import ToolRegistry, ToolDefinition
    from core.tool_executor import ToolExecutor

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="fs_apply",
            description="apply",
            parameters={"type": "object", "properties": {"ops": {"type": "array"}}, "required": ["ops"]},
            handler=lambda ops: "ok",
            safety_level="SAFE",
        )
    )
    ex = ToolExecutor(tool_registry=reg, workspace_dir=str(tmp_path / "ws"))

    args = {"ops": [{"op": "delete", "target": "~/b.txt"}]}
    res = asyncio.run(ex.execute("fs_apply", args))
    assert res.success is False
    assert res.error_type == "NeedConfirmation"
    # Ensure the preview includes normalized op/path.
    assert "\"op\": \"trash\"" in (res.error_message or "")


def test_normalize_exec_cmd_key(tmp_path):
    from core.tool_registry import ToolRegistry, ToolDefinition
    from core.tool_executor import ToolExecutor

    seen = {}

    def _handler(command, timeout=30):
        seen["command"] = command
        return "ok"

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="exec",
            description="exec",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            handler=_handler,
            safety_level="SAFE",
        )
    )
    ex = ToolExecutor(tool_registry=reg, workspace_dir=str(tmp_path / "ws"))
    res = asyncio.run(ex.execute("exec", {"cmd": "echo hi"}))
    assert res.success is True
    assert seen["command"] == "echo hi"

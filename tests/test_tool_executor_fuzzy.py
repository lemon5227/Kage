import asyncio


def test_fuzzy_matches_known_tool_name(tmp_path):
    from core.tool_registry import ToolRegistry, ToolDefinition
    from core.tool_executor import ToolExecutor

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="skills_find_remote",
            description="x",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=lambda query, max_results=5: "ok",
            safety_level="SAFE",
        )
    )
    ex = ToolExecutor(tool_registry=reg, workspace_dir=str(tmp_path / "ws"))

    # Misspelled tool name should be corrected.
    res = asyncio.run(ex.execute("skills_find_remot", {"query": "a"}))
    assert res.success is True
    assert res.name == "skills_find_remote"


def test_fuzzy_does_not_map_to_exec(tmp_path):
    from core.tool_registry import ToolRegistry, ToolDefinition
    from core.tool_executor import ToolExecutor

    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="exec",
            description="exec",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            handler=lambda command, timeout=30: "ok",
            safety_level="SAFE",
        )
    )
    ex = ToolExecutor(tool_registry=reg, workspace_dir=str(tmp_path / "ws"))

    # Similar strings should not get auto-mapped into `exec`.
    res = asyncio.run(ex.execute("exex", {"command": "echo hi"}))
    assert res.success is False
    assert res.error_type == "UnknownTool"

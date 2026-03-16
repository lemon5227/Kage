import json
import os


def test_fs_move_and_undo(tmp_path, monkeypatch):
    from core.tools_impl import fs_move, fs_undo_last

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))

    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    f = src_dir / "a.txt"
    f.write_text("hi", encoding="utf-8")

    res = json.loads(fs_move(str(f), str(dest_dir), workspace_dir=str(ws)))
    assert res["success"] is True
    moved_to = res["moved"]["to"]
    assert os.path.exists(moved_to)
    assert not os.path.exists(str(f))

    undo = json.loads(fs_undo_last(workspace_dir=str(ws)))
    assert undo["success"] is True
    # Restored back to original path (or conflict path if existed)
    assert os.path.exists(str(f)) or any(u.get("to") == str(f) for u in undo.get("undone", []))


def test_fs_write_creates_backup_and_undo(tmp_path):
    from core.tools_impl import fs_write, fs_undo_last

    ws = tmp_path / "ws"
    ws.mkdir()

    p = tmp_path / "note.txt"
    p.write_text("old", encoding="utf-8")

    res = json.loads(fs_write(str(p), "new", workspace_dir=str(ws)))
    assert res["success"] is True
    assert p.read_text(encoding="utf-8") == "new"

    undo = json.loads(fs_undo_last(workspace_dir=str(ws)))
    assert undo["success"] is True
    assert p.read_text(encoding="utf-8") == "old"


def test_tool_executor_exec_rm_requires_confirmation(tmp_path):
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

    import asyncio

    r = asyncio.run(ex.execute("exec", {"command": "rm -rf /tmp/nope"}))
    assert r.success is False
    assert r.error_type == "NeedConfirmation"


def test_tool_executor_fs_apply_with_trash_requires_confirmation(tmp_path):
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

    import asyncio

    r = asyncio.run(ex.execute("fs_apply", {"ops": [{"op": "trash", "path": "/tmp/x"}]}))
    assert r.success is False
    assert r.error_type == "NeedConfirmation"

import json


def test_shortcuts_list_missing_dependency(monkeypatch):
    import subprocess
    from core.tools_impl import shortcuts_list

    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = json.loads(shortcuts_list())
    assert out["success"] is False
    assert out["error"] == "MissingDependency"


def test_shortcuts_run_missing_dependency(monkeypatch):
    import subprocess
    from core.tools_impl import shortcuts_run

    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = json.loads(shortcuts_run("x"))
    assert out["success"] is False
    assert out["error"] == "MissingDependency"


def test_registry_includes_shortcuts_tools():
    from core.tool_registry import create_default_registry

    reg = create_default_registry(memory_system=None)
    assert reg.has_tool("shortcuts_list")
    assert reg.has_tool("shortcuts_run")
    assert reg.has_tool("shortcuts_view")

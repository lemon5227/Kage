"""T10: a promoted skill enters daily use only via user consent, in a fixed namespace."""

import asyncio
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.evolution.sandbox import ProcessSkillRunner
from core.evolution.search import run_search
from core.skill_adoption import SkillAdoption
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolDefinition, ToolRegistry, create_default_registry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def promoted(tmp_path_factory):
    """A real candidate promoted by the fixture search loop (no Docker)."""
    tmp = tmp_path_factory.mktemp("search")
    config = json.loads((ROOT / "eval/evolution/pilot.json").read_text())
    config["output_dir"] = str(tmp / "runs")
    path = tmp / "pilot.json"
    path.write_text(json.dumps(config))
    report = run_search(path, "fixture", "process")
    assert report["comparisons"][0]["promoted"] is True
    return report["active_candidate"]


def _adoption(tmp_path, registry=None):
    return SkillAdoption(registry or ToolRegistry(), workspace_dir=str(tmp_path),
                         runner_factory=lambda: ProcessSkillRunner(timeout_s=5))


def test_register_custom_enforces_namespace_and_no_override():
    registry = create_default_registry()
    tool = ToolDefinition(name="custom_x", description="d", parameters={"type": "object"}, handler=lambda: "")
    registry.register_custom(tool)
    with pytest.raises(ValueError):
        registry.register_custom(tool)
    with pytest.raises(ValueError):
        registry.register_custom(ToolDefinition(name="get_time", description="d",
                                                parameters={"type": "object"}, handler=lambda: ""))
    assert registry.unregister("custom_x") and not registry.has_tool("custom_x")


def test_adopt_registers_snapshot_tool_and_executes_out_of_process(tmp_path, promoted):
    registry = ToolRegistry()
    adoption = _adoption(tmp_path, registry)
    row = adoption.adopt(promoted, source_run="r1")
    assert row["tools"] and all(name.startswith("custom_") for name in row["tools"])
    assert Path(row["snapshot"]).is_dir() and Path(row["snapshot"]).parent == tmp_path / "skills" / "adopted"
    assert row["tools"] == ["custom_normalize"]
    executor = ToolExecutor(registry, workspace_dir=str(tmp_path))
    workspace = tmp_path / "skills" / "workspace"
    (workspace / "in.json").write_text(json.dumps([{"name": "  Ada ", "age": 36}]))
    ok = asyncio.run(executor.execute("custom_normalize", {"input_file": "in.json", "output_file": "out.json"}))
    assert ok.success, ok.result
    assert json.loads((workspace / "out.json").read_text()) == [{"name": "Ada", "age": 36}]
    # Arguments the skill schema rejects never reach the skill.
    bad = asyncio.run(executor.execute("custom_normalize", {"input_file": "in.json"}))
    assert json.loads(bad.result)["error"] == "InvalidArgument"
    assert adoption.adopted()[0]["digest"] == promoted["digest"]


def test_adopt_rejects_changed_bundle_and_duplicates(tmp_path, promoted):
    copy = tmp_path / "bundle"
    shutil.copytree(promoted["bundle_path"], copy)
    tampered = {**promoted, "bundle_path": str(copy)}
    for py in copy.glob("*.py"):
        py.write_text(py.read_text() + "\n# tampered\n")
    with pytest.raises(ValueError, match="changed"):
        _adoption(tmp_path / "a").adopt(tampered)
    adoption = _adoption(tmp_path / "b")
    adoption.adopt(promoted)
    with pytest.raises(ValueError, match="already"):
        adoption.adopt(promoted)
    with pytest.raises(ValueError):
        adoption.adopt({**promoted, "digest": "../../etc"})


def test_restore_reverifies_and_revoke_unregisters(tmp_path, promoted):
    first = _adoption(tmp_path)
    row = first.adopt(promoted)
    registry = ToolRegistry()
    restored = _adoption(tmp_path, registry).restore()
    assert restored == row["tools"] and registry.has_tool(restored[0])

    # A snapshot edited after adoption is not restored.
    for py in Path(row["snapshot"]).glob("*.py"):
        py.write_text(py.read_text() + "\n# edited\n")
    assert _adoption(tmp_path, ToolRegistry()).restore() == []

    again = _adoption(tmp_path, registry)
    assert again.revoke(row["digest"]) and not registry.has_tool(restored[0])
    assert again.adopted() == []


def test_adopted_tools_are_visible_without_unclassified_warning():
    from core.tool_visibility import select
    decision = select("帮我整理一下", "chat", {"get_time", "custom_sum_csv"})
    assert "custom_sum_csv" in decision.names and decision.unclassified == ()


def _server(tmp_path, scheduler_rows):
    from core.server import KageServer
    server = object.__new__(KageServer)
    server.evolution_scheduler = MagicMock()
    server.evolution_scheduler.runs.return_value = scheduler_rows
    server.skill_adoption = _adoption(tmp_path)
    sent = []

    async def send_message(type_, data):
        sent.append((type_, data))

    server.send_message = send_message
    return server, sent


def test_server_adopts_only_promoted_candidate_from_scheduler_log(tmp_path, promoted):
    rows = [{"event": "finished", "run_id": "r1", "promoted": True, "active_candidate": promoted},
            {"event": "finished", "run_id": "r2", "promoted": False, "active_candidate": None}]
    server, sent = _server(tmp_path, rows)
    asyncio.run(server._adopt_skill({"type": "adopt_skill", "run_id": "r2"}))
    assert sent[-1][1]["event"] == "skill_adoption_failed"
    asyncio.run(server._adopt_skill({"type": "adopt_skill", "run_id": "r1"}))
    assert sent[-1][1]["event"] == "skill_adopted" and sent[-1][1]["tools"]

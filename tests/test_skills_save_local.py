"""Contract tests for skills_save_local.

The function previously took ``(skill_name, content, workspace_dir)`` while the
registered tool schema advertised ``name/description/body/target_dir/overwrite``, so
every model-issued call raised ``TypeError: unexpected keyword argument 'name'`` —
and the agent's skill-autosave path (``core/agentic_loop.py``) silently failed on
every run. It also interpolated the name into a path, so ``../../x`` escaped the
skills directory.
"""

import json
from pathlib import Path

from core.tools_impl import skills_save_local


def test_creates_skill_file_with_frontmatter(tmp_path):
    out = json.loads(skills_save_local(name="my-skill", description="演示技能",
                                       body="# My Skill\nStep 1", target_dir=str(tmp_path)))

    assert out["success"] is True
    written = Path(out["path"])
    assert written == tmp_path.resolve() / "my-skill.md"
    text = written.read_text(encoding="utf-8")
    assert text.startswith("---\nname: my-skill\n")
    assert "演示技能" in text
    assert "Step 1" in text


def test_second_save_requires_explicit_overwrite(tmp_path):
    skills_save_local(name="my-skill", description="d", body="v1", target_dir=str(tmp_path))
    refused = json.loads(skills_save_local(name="my-skill", description="d", body="v2",
                                           target_dir=str(tmp_path)))
    assert refused["success"] is False
    assert refused["error"] == "AlreadyExists"

    replaced = json.loads(skills_save_local(name="my-skill", description="d", body="v2",
                                            target_dir=str(tmp_path), overwrite=True))
    assert replaced["success"] is True
    assert "v2" in (tmp_path / "my-skill.md").read_text(encoding="utf-8")


def test_name_is_normalized_and_validated(tmp_path):
    out = json.loads(skills_save_local(name="  My-Skill  ", description="d",
                                       target_dir=str(tmp_path)))
    assert out["success"] is True
    assert out["name"] == "my-skill"


def test_path_traversal_is_rejected(tmp_path):
    for evil in ("../../evil", "a/b", "..", "", "bad name", "x" * 65):
        out = json.loads(skills_save_local(name=evil, description="d", target_dir=str(tmp_path)))
        assert out["success"] is False, evil
        assert out["error"] == "InvalidArgument", evil
    assert not (tmp_path.parent / "evil.md").exists()


def test_empty_description_is_rejected(tmp_path):
    out = json.loads(skills_save_local(name="ok", description="  ", target_dir=str(tmp_path)))
    assert out["success"] is False
    assert out["error"] == "InvalidArgument"


def test_autosave_call_shape_from_agentic_loop_works(tmp_path):
    """The exact argument shape core/agentic_loop.py sends must succeed."""
    save_args = {"name": "auto-web_fetch-ab12cd", "description": "重复请求自动沉淀：x",
                 "body": "## Goal\nx"}
    out = json.loads(skills_save_local(target_dir=str(tmp_path), **save_args))
    assert out["success"] is True


def test_registered_tool_rejects_target_dir_outside_skill_dirs(tmp_path, monkeypatch):
    """T13: the model-facing tool may only write into Kage's skill directories."""
    from core.tool_registry import create_default_registry
    from core.tools import skill_ops

    allowed = tmp_path / "home" / ".kage" / "skills"
    monkeypatch.setattr(skill_ops, "_allowed_skill_roots", lambda: [allowed.resolve()])
    handler = create_default_registry().get_handler("skills_save_local")

    for bad in (str(tmp_path / "elsewhere"), str(allowed / ".." / ".." / "x"), "/tmp"):
        out = json.loads(handler(name="s", description="d", target_dir=bad))
        assert out["success"] is False and out["error"] == "InvalidArgument", bad
    assert not list(tmp_path.rglob("s.md"))

    ok = json.loads(handler(name="s", description="d", target_dir=str(allowed / "team")))
    assert ok["success"] is True and (allowed / "team" / "s.md").is_file()

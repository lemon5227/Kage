import json


def test_skills_save_local_creates_skill(tmp_path):
    from core.tools_impl import skills_save_local

    out = json.loads(skills_save_local("my-skill", "# My Skill\nStep 1", workspace_dir=str(tmp_path)))
    assert out["success"] is True
    assert "path" in out


def test_skills_save_local_overwrites(tmp_path):
    from core.tools_impl import skills_save_local

    skills_save_local("my-skill", "v1", workspace_dir=str(tmp_path))
    out = json.loads(skills_save_local("my-skill", "v2", workspace_dir=str(tmp_path)))
    assert out["success"] is True

import json


def test_skills_save_local_creates_skill(tmp_path):
    from core.tools_impl import skills_save_local

    out = json.loads(
        skills_save_local(
            name="my-skill",
            description="desc",
            body="Step 1",
            target_dir=str(tmp_path),
            overwrite=False,
        )
    )
    assert out["success"] is True
    assert out["created"] is True
    assert out["name"] == "my-skill"


def test_skills_save_local_no_overwrite(tmp_path):
    from core.tools_impl import skills_save_local

    _ = skills_save_local("my-skill", "desc", "", target_dir=str(tmp_path), overwrite=False)
    out = json.loads(skills_save_local("my-skill", "desc2", "", target_dir=str(tmp_path), overwrite=False))
    assert out["success"] is True
    assert out["created"] is False

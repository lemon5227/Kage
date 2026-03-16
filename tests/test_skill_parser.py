import textwrap


def test_parse_skill_file_frontmatter(tmp_path):
    from core.skill_parser import parse_skill_file

    p = tmp_path / "SKILL.md"
    p.write_text(
        textwrap.dedent(
            """\
            ---
            name: find-skills
            description: Find and install skills from skills.sh
            ---

            # Find Skills

            Some content.
            """
        ),
        encoding="utf-8",
    )

    info = parse_skill_file(str(p))
    assert info is not None
    assert info.name == "find-skills"
    assert info.title == "Find Skills"
    assert "skills.sh" in info.description


def test_parse_skill_file_legacy(tmp_path):
    from core.skill_parser import parse_skill_file

    p = tmp_path / "youtube_search.md"
    p.write_text(
        textwrap.dedent(
            """\
            # YouTube 搜索

            ## 描述

            用于搜索视频并打开。

            ## 使用场景

            - 查找某个人最新视频
            """
        ),
        encoding="utf-8",
    )

    info = parse_skill_file(str(p))
    assert info is not None
    assert info.title == "YouTube 搜索"
    assert "搜索视频" in info.description
    # Legacy name is slugified; just ensure non-empty.
    assert isinstance(info.name, str) and info.name


def test_scan_skills_directory_recurses_for_skill_md(tmp_path):
    from core.skill_parser import scan_skills_directory

    root = tmp_path / "skills"
    (root / "foo").mkdir(parents=True)
    (root / "foo" / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: foo-skill
            description: Foo skill
            ---
            
            # Foo Skill
            """
        ),
        encoding="utf-8",
    )

    infos = scan_skills_directory(str(root))
    assert any(i.name == "foo-skill" for i in infos)


def test_parse_skills_find_output():
    from core.tools_impl import _parse_skills_find_output

    sample = textwrap.dedent(
        """\
        Install with npx skills add <owner/repo@skill>

        vercel-labs/skills@find-skills
        └ https://skills.sh/vercel-labs/skills/find-skills

        vercel-labs/agent-skills@web-design-guidelines
        └ https://skills.sh/vercel-labs/agent-skills/web-design-guidelines
        """
    )

    results = _parse_skills_find_output(sample, max_results=5)
    assert results
    assert results[0]["ref"] == "vercel-labs/skills@find-skills"
    assert results[0]["url"].startswith("https://skills.sh/")

from core.tool_registry import create_default_registry


def test_default_registry_includes_skills_tools():
    reg = create_default_registry(memory_system=None)
    for name in [
        "skills_find_remote",
        "skills_install",
        "skills_list",
        "skills_read",
    ]:
        assert reg.has_tool(name)

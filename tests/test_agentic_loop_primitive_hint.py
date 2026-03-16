from core.agentic_loop import AgenticLoop


def test_primitive_hint_file_search():
    h = AgenticLoop._primitive_tool_hint("帮我找一下report在哪里")
    assert "fs_search" in h


def test_primitive_hint_system_control():
    h = AgenticLoop._primitive_tool_hint("把音量调大")
    assert "system_control" in h


def test_primitive_hint_fs_apply():
    h = AgenticLoop._primitive_tool_hint("把下载文件夹整理一下")
    assert "fs_apply" in h

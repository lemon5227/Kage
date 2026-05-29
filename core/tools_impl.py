"""
Core tool implementations — backward compatibility layer.

This module re-exports all tools from the domain-specific modules
in core.tools/. It exists solely for backward compatibility so that
existing imports (from core.tools_impl import xxx) continue to work.

New code should import from core.tools directly:
    from core.tools import fs_move, web_fetch, ...
"""

# Re-export from the new modular structure for backward compatibility.
# Explicit imports + __all__ keep static analyzers happy and provide a stable API.
from core.tools import (
    fs_move, fs_rename, fs_write, fs_trash, fs_undo_last,
    fs_search, fs_preview, fs_apply,
    tavily_search, web_fetch, smart_search, search, search_and_open,
    parse_duckduckgo_html, exec_command, open_url, open_app,
    open_website, take_screenshot, get_time,
    system_control, system_capabilities,
    find_skills, skills_find_remote, skills_install, skills_list,
    skills_read, skills_save_local, ensure_node_tools, run_npx,
    parse_skills_find_output,
    shortcuts_list, shortcuts_run, shortcuts_create,
    shortcuts_delete, shortcuts_view, shortcuts_bootstrap_kage,
    memory_search, proactive_agent,
    HTMLTextExtractor, strip_html_tags, truncate_output,
    MAX_OUTPUT_LENGTH, TRUNCATION_MARKER,
)

__all__ = [
    "fs_move", "fs_rename", "fs_write", "fs_trash", "fs_undo_last",
    "fs_search", "fs_preview", "fs_apply",
    "tavily_search", "web_fetch", "smart_search", "search", "search_and_open",
    "parse_duckduckgo_html", "exec_command", "open_url", "open_app",
    "open_website", "take_screenshot", "get_time",
    "system_control", "system_capabilities",
    "find_skills", "skills_find_remote", "skills_install", "skills_list",
    "skills_read", "skills_save_local", "ensure_node_tools", "run_npx",
    "parse_skills_find_output",
    "shortcuts_list", "shortcuts_run", "shortcuts_create",
    "shortcuts_delete", "shortcuts_view", "shortcuts_bootstrap_kage",
    "memory_search", "proactive_agent",
    "HTMLTextExtractor", "strip_html_tags", "truncate_output",
    "MAX_OUTPUT_LENGTH", "TRUNCATION_MARKER",
]

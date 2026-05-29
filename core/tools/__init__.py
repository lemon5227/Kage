"""Core tools package — re-exports for backward compatibility.

This module provides a drop-in replacement for core.tools_impl.
All public functions are re-exported from their domain-specific modules.
"""

# File operations
from core.tools.file_ops import (
    fs_move, fs_rename, fs_write, fs_trash, fs_undo_last,
    fs_search, fs_preview, fs_apply,
)

# Web and search operations
from core.tools.web_ops import (
    tavily_search, web_fetch, smart_search, search, search_and_open,
    parse_duckduckgo_html, exec_command, open_url, open_app,
    open_website, take_screenshot, get_time,
    system_control, system_capabilities,
)

# Skill management
from core.tools.skill_ops import (
    find_skills, skills_find_remote, skills_install, skills_list,
    skills_read, skills_save_local, ensure_node_tools, run_npx,
    parse_skills_find_output,
)

# Shortcuts
from core.tools.shortcuts_ops import (
    shortcuts_list, shortcuts_run, shortcuts_create,
    shortcuts_delete, shortcuts_view, shortcuts_bootstrap_kage,
)

# Memory
from core.tools.memory_ops import memory_search

# Agent
from core.tools.agent_ops import proactive_agent

# HTML utilities
from core.tools.html_ops import HTMLTextExtractor, strip_html_tags, truncate_output

# Constants (backward compat)
from core.tools.html_ops import MAX_OUTPUT_LENGTH, TRUNCATION_MARKER

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

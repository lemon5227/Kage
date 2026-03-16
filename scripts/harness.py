"""scripts.harness

Developer harness helpers for running Kage core without the GUI.

These helpers reflect the current architecture (AgenticLoop + ToolExecutor).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_repo_root_on_path() -> str:
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


def make_tool_executor(workspace_dir: str = "~/.kage"):
    ensure_repo_root_on_path()
    from core.tool_registry import create_default_registry
    from core.tool_executor import ToolExecutor

    reg = create_default_registry(memory_system=None)
    return ToolExecutor(tool_registry=reg, workspace_dir=workspace_dir)


def make_agentic_loop(settings_path: str = "config/settings.json"):
    ensure_repo_root_on_path()

    from core.identity_store import IdentityStore
    from core.memory import MemorySystem
    from core.session_manager import SessionManager
    from core.tool_registry import create_default_registry
    from core.tool_executor import ToolExecutor
    from core.prompt_builder import PromptBuilder
    from core.model_provider import create_provider_from_settings

    from core.agentic_loop import AgenticLoop

    identity = IdentityStore()
    identity.ensure_files_exist()

    memory = MemorySystem()
    session = SessionManager()
    try:
        session.load_from_file()
    except Exception:
        pass

    registry = create_default_registry(memory_system=memory)
    executor = ToolExecutor(tool_registry=registry)

    model_provider = create_provider_from_settings(settings_path=settings_path)

    prompt_builder = PromptBuilder(
        identity_store=identity,
        memory_system=memory,
        tool_registry=registry,
    )

    return AgenticLoop(
        model_provider=model_provider,
        tool_executor=executor,
        prompt_builder=prompt_builder,
        session_manager=session,
    )

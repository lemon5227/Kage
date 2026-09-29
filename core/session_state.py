from __future__ import annotations

from typing import Any
from core.session_manager import SessionManager


class SessionState(SessionManager):
    """Short-term session state for multi-turn conversation.

    Unified with SessionManager as Single Source of Truth (SSOT).
    When created without workspace_dir, operates purely in-memory.
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        history: Any = None,
        pending_action: Any | None = None,
        last_action: Any | None = None,
        persist: bool | None = None,
    ):
        should_persist = persist if persist is not None else bool(workspace_dir)
        super().__init__(workspace_dir=workspace_dir or "", persist=should_persist)
        self.pending_action = pending_action
        self.last_action = last_action
        if history:
            for item in history:
                if isinstance(item, dict) and "role" in item and "content" in item:
                    self.add_turn(item["role"], item["content"])

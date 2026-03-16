from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections import deque


@dataclass
class SessionState:
    """Short-term session state for multi-turn conversation.

    This state should be cheap to update and safe to reset.
    """

    history: deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=12))
    pending_action: Any | None = None
    last_action: Any | None = None

    def add_turn(self, role: str, content: str) -> None:
        role = str(role or "").strip()
        if role not in ("user", "assistant"):
            return
        content = str(content or "").strip()
        if not content:
            return
        self.history.append({"role": role, "content": content})

    def as_history_list(self) -> list[dict[str, str]]:
        try:
            return list(self.history)
        except Exception:
            return []

    def has_pending_action(self) -> bool:
        return self.pending_action is not None

    def set_pending_action(self, pending: Any) -> Any:
        self.pending_action = pending
        return pending

    def clear_pending_action(self) -> None:
        self.pending_action = None

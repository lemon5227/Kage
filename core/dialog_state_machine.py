from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.interaction_state import pending_kind
from core.pending_handlers import PendingHandlerResult
from core.session_state import SessionState


@dataclass(frozen=True)
class DialogStateSnapshot:
    pending_action: Any | None
    pending_kind: str

    @property
    def phase(self) -> str:
        if self.pending_action is None:
            return "idle"
        if self.pending_kind.startswith("confirm_"):
            return "awaiting_confirmation"
        return "awaiting_followup"


class DialogStateMachine:
    """Minimal state wrapper for pending-action lifecycle.

    This keeps behavior unchanged while centralizing state mutations.
    """

    def __init__(self, session: SessionState):
        self._session = session

    def snapshot(self) -> DialogStateSnapshot:
        pending = self._session.pending_action
        return DialogStateSnapshot(
            pending_action=pending,
            pending_kind=pending_kind(pending) if pending is not None else "",
        )

    def set_pending(self, pending: Any) -> Any:
        return self._session.set_pending_action(pending)

    def clear_pending(self) -> None:
        self._session.clear_pending_action()

    def apply_pending_result(self, result: PendingHandlerResult) -> None:
        if result.set_pending is not None:
            self.set_pending(result.set_pending)
        elif result.clear_pending:
            self.clear_pending()

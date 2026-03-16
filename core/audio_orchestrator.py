from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AudioListenOutcome:
    text: str = ""
    emotion: str = "neutral"

    @property
    def has_input(self) -> bool:
        return bool(self.text)


@dataclass(frozen=True)
class AudioIdleDecision:
    next_ui_state: str
    keep_in_conversation: bool
    sleep_sec: float


class AudioOrchestrator:
    """Encapsulates current audio control policy.

    This is intentionally policy-oriented rather than backend-specific so the
    current half-duplex implementation can evolve toward streaming ASR and
    duplex behavior without growing server.py further.
    """

    def __init__(self, *, wakeword_enabled_cfg: bool):
        self._wakeword_enabled_cfg = bool(wakeword_enabled_cfg)

    def is_always_listen_mode(self, ears: Any) -> bool:
        return (not self._wakeword_enabled_cfg) or (not bool(getattr(ears, "wakeword_enabled", False)))

    def should_wait_for_wakeword(self, *, in_conversation: bool, ears: Any) -> bool:
        return (not in_conversation) and (not self.is_always_listen_mode(ears))

    @staticmethod
    def normalize_listen_result(listen_result: Any) -> AudioListenOutcome:
        if isinstance(listen_result, tuple):
            text = str(listen_result[0] or "").strip()
            emotion = str(listen_result[1] or "neutral").strip() or "neutral"
            return AudioListenOutcome(text=text, emotion=emotion)
        return AudioListenOutcome(text=str(listen_result or "").strip(), emotion="neutral")

    def decide_after_empty_input(self, *, in_conversation: bool, ears: Any) -> AudioIdleDecision:
        if self.is_always_listen_mode(ears):
            return AudioIdleDecision(
                next_ui_state="LISTENING",
                keep_in_conversation=in_conversation,
                sleep_sec=0.05,
            )
        return AudioIdleDecision(
            next_ui_state="IDLE",
            keep_in_conversation=False,
            sleep_sec=0.1,
        )

    @staticmethod
    def should_interrupt_for_text_input(ui_state: str) -> bool:
        return str(ui_state or "") == "SPEAKING"

    @staticmethod
    def should_enable_voice_barge_in(*, text_only_mode: bool, ears: Any) -> bool:
        return (not text_only_mode) and (ears is not None) and hasattr(ears, "detect_voice_activity")

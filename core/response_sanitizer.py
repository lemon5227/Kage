from __future__ import annotations

import re


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_INCOMPLETE_THINK_RE = re.compile(r"<think>.*$", flags=re.DOTALL | re.IGNORECASE)
_SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>",
    flags=re.IGNORECASE | re.DOTALL,
)
_MODEL_TOKEN_RE = re.compile(r"<\|[^>]+\|>")
_THINKING_PREAMBLE_RE = re.compile(r"^\s*thinking\s+process\s*:\s*", flags=re.IGNORECASE)
_FINAL_ANSWER_MARKERS = (
    "final answer:",
    "answer:",
    "response:",
    "最终回答：",
    "最终答案：",
    "答案：",
)


def strip_reasoning_artifacts(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = str(text)
    cleaned = _THINK_BLOCK_RE.sub("", cleaned)
    cleaned = _INCOMPLETE_THINK_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return ""

    if _THINKING_PREAMBLE_RE.match(cleaned):
        lower = cleaned.lower()
        for marker in _FINAL_ANSWER_MARKERS:
            idx = lower.find(marker)
            if idx >= 0:
                return cleaned[idx + len(marker):].strip()
        return ""

    return cleaned


def sanitize_for_speech_text(text: str | None) -> str:
    if text is None:
        return ""
    s = strip_reasoning_artifacts(text)
    s = _SYSTEM_REMINDER_RE.sub("", s)
    s = _MODEL_TOKEN_RE.sub("", s)
    s = " ".join(s.split())
    return s.strip()

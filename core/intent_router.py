"""core.intent_router

Tiny, deterministic intent router for very high-confidence commands.

We use this to minimize model calls and latency for commands that should never
require LLM reasoning (e.g., undo).
"""

from __future__ import annotations


def is_undo_request(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    # Common Chinese phrases
    if "撤销" in s or "撤回" in s or "回滚" in s:
        return True
    # Short English
    if s in ("undo", "rollback"):
        return True
    # Colloquial
    if s in ("后悔了", "算了撤销"):
        return True
    return False

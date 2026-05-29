"""core.router

Legacy lightweight intent router.

This module exists primarily for backwards-compatibility with older unit tests.
The runtime now prefers the agentic loop + tool schemas for routing.
"""

from __future__ import annotations

import re


# Hoisted patterns (precompiled once instead of recompiled on every classify call).
_RE_SCREENSHOT = re.compile(r"截图|截屏|截个屏")
_RE_OPEN_APP = re.compile(r"^(开|打开|开启|启动)\s*\S+")
_OPEN_APP_NEGATIVE_KEYWORDS = ("网站", "网页", "http", ".com", "搜", "查", "找")


class KageRouter:
    """Very small keyword-based classifier.

    Returns:
      - "COMMAND" for high-confidence command-like requests
      - "CHAT" otherwise
    """

    def classify(self, text: str) -> str:
        s = str(text or "").strip()
        if not s:
            return "CHAT"

        low = s.lower()

        # Screenshot intents
        if _RE_SCREENSHOT.search(s):
            return "COMMAND"

        # Open app intents (high confidence, short imperative)
        if _RE_OPEN_APP.search(s):
            # Avoid misclassifying web/search requests
            if any(k in low for k in _OPEN_APP_NEGATIVE_KEYWORDS):
                return "CHAT"
            return "COMMAND"

        return "CHAT"

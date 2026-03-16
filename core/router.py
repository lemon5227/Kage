"""core.router

Legacy lightweight intent router.

This module exists primarily for backwards-compatibility with older unit tests.
The runtime now prefers the agentic loop + tool schemas for routing.
"""

from __future__ import annotations

import re


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
        if re.search(r"截图|截屏|截个屏", s):
            return "COMMAND"

        # Open app intents (high confidence, short imperative)
        if re.search(r"^(开|打开|开启|启动)\s*\S+", s):
            # Avoid misclassifying web/search requests
            if any(k in low for k in ["网站", "网页", "http", ".com", "搜", "查", "找"]):
                return "CHAT"
            return "COMMAND"

        return "CHAT"

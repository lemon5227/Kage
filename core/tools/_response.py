"""Shared JSON response helpers for tool functions.

Standardizes the response shape across all tools to reduce inconsistencies
that previously forced callers (agentic_loop) to guess whether a "success"
key existed in the returned JSON.

All responses now have shape:
  Success: {"success": True, ...payload}
  Error:   {"success": False, "error": str, "message": str}
"""

import json
from typing import Any


def ok(**payload: Any) -> str:
    """Build a success JSON response."""
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def err(error: str, message: str = "") -> str:
    """Build an error JSON response.

    Args:
        error: Short error code (e.g. "Timeout", "InvalidInput", "PathBlocked").
        message: Human-readable explanation.
    """
    payload: dict[str, Any] = {"success": False, "error": error}
    if message:
        payload["message"] = message
    return json.dumps(payload, ensure_ascii=False)

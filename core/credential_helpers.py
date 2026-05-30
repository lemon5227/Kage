"""Credential helpers — detect cloud LLM keys from the user environment.

Goals:
  * Help users who already have Claude Code or the OpenAI CLI installed
    get going with one click — Kage can pick up their already-configured
    `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env var.
  * Stay strictly env-var based. We do **not** read CLI credential files
    (e.g. `~/.claude/`, `~/.openai/`) because:
      - those files often contain OAuth tokens scoped to the CLI's client id
        and not valid against the public REST API,
      - the file format is undocumented and may break,
      - silently reading credential files surprises users.
  * Never echo a detected key back to the UI; return only booleans + a
    user-friendly source label.

Public surface:

    detect_provider_credentials() -> dict
        Returns a {provider: {present: bool, source: str}} mapping that
        the settings UI consumes.
"""

from __future__ import annotations

import os
from typing import Optional


# Each entry: (env_var_name, label_when_found)
# Multiple env vars per provider lets us recognise both the official name
# and common aliases (e.g. Claude Code historically accepted both
# `ANTHROPIC_API_KEY` and `CLAUDE_API_KEY`).
_ANTHROPIC_KEYS = (
    ("ANTHROPIC_API_KEY", "Anthropic SDK / Claude Code"),
    ("CLAUDE_API_KEY", "Claude (legacy)"),
)
_OPENAI_KEYS = (
    ("OPENAI_API_KEY", "OpenAI SDK / Codex CLI"),
)
_GOOGLE_KEYS = (
    ("GOOGLE_API_KEY", "Google AI Studio"),
    ("GEMINI_API_KEY", "Gemini"),
)
_DEEPSEEK_KEYS = (
    ("DEEPSEEK_API_KEY", "DeepSeek"),
)
_MOONSHOT_KEYS = (
    ("MOONSHOT_API_KEY", "Moonshot Kimi"),
)


def _first_present(pairs: tuple[tuple[str, str], ...], env: dict) -> tuple[bool, str]:
    """Return (present, source_label) for the first env var that exists."""
    for var, label in pairs:
        if str(env.get(var) or "").strip():
            return True, label
    return False, ""


def detect_provider_credentials(env: Optional[dict] = None) -> dict[str, dict[str, str | bool]]:
    """Detect which cloud-provider API keys are visible in the environment.

    Args:
        env: Optional override for `os.environ`, primarily for tests.

    Returns:
        {
          "anthropic": {"present": True, "source": "Anthropic SDK / Claude Code"},
          "openai":    {"present": False, "source": ""},
          "google":    {"present": False, "source": ""},
          ...
        }

    The returned dict NEVER contains the actual API key value.
    """
    e = os.environ if env is None else env

    out: dict[str, dict[str, str | bool]] = {}
    for name, pairs in (
        ("anthropic", _ANTHROPIC_KEYS),
        ("openai", _OPENAI_KEYS),
        ("google", _GOOGLE_KEYS),
        ("deepseek", _DEEPSEEK_KEYS),
        ("moonshot", _MOONSHOT_KEYS),
    ):
        present, source = _first_present(pairs, e)
        out[name] = {"present": present, "source": source}
    return out


def read_provider_credential(provider: str, env: Optional[dict] = None) -> str:
    """Return the raw API key from environment for a given provider, or "".

    Internal helper — callers (server endpoints) should validate the
    request and apply this server-side. The key is never sent back to
    the UI; it's stored to settings.json and used by the broker.

    Args:
        provider: One of "anthropic", "openai", "google", "deepseek",
            "moonshot".
        env: Optional override for `os.environ`.
    """
    e = os.environ if env is None else env
    pairs = {
        "anthropic": _ANTHROPIC_KEYS,
        "openai": _OPENAI_KEYS,
        "google": _GOOGLE_KEYS,
        "deepseek": _DEEPSEEK_KEYS,
        "moonshot": _MOONSHOT_KEYS,
    }.get(str(provider or "").strip().lower())
    if not pairs:
        return ""
    for var, _label in pairs:
        v = str(e.get(var) or "").strip()
        if v:
            return v
    return ""

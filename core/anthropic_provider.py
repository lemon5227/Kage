"""AnthropicProvider — native Claude messages API.

Wraps `https://api.anthropic.com/v1/messages` so users with an
`ANTHROPIC_API_KEY` (e.g. set by Claude Code / Anthropic CLI) can route
their cloud calls through Anthropic without going via an OpenAI-compat
shim.

Returns the same `ModelResponse` shape as `OpenAICompatibleProvider` so
the rest of Kage (broker, hybrid, agentic loop) does not need to know
which vendor served the request.

Differences from OpenAI handled here:
  * `system` is a top-level field, not a message.
  * Messages must alternate user/assistant; consecutive messages of the
    same role are merged.
  * `max_tokens` is required (no default).
  * Tool calls are returned as `content` blocks of type `tool_use`, not
    inside a separate `tool_calls` array.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from core.model_provider import ModelProvider, ModelResponse
from core.trace import log

logger = logging.getLogger(__name__)


_DEFAULT_API_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-3-5-haiku-latest"
_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


def _coerce_text_content(content: Any) -> str:
    """Flatten OpenAI-style content (str or multi-part) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return str(content)


def _convert_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert OpenAI-style messages → (system_prompt, anthropic_messages).

    Anthropic requires:
      * a single `system` string (we concatenate any system messages),
      * alternating user / assistant messages.

    Consecutive same-role messages are merged with newline separators so
    we always satisfy the alternation rule.
    """
    system_parts: list[str] = []
    anthropic_msgs: list[dict] = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        text = _coerce_text_content(msg.get("content"))

        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role not in ("user", "assistant"):
            # Tool-result and other roles are ignored at this layer; the
            # agentic loop already includes tool output in user messages.
            continue
        if not text:
            continue

        if anthropic_msgs and anthropic_msgs[-1]["role"] == role:
            # Same role twice in a row — merge into the previous message.
            anthropic_msgs[-1]["content"] += "\n" + text
        else:
            anthropic_msgs.append({"role": role, "content": text})

    system_prompt = "\n\n".join(p for p in system_parts if p)
    return system_prompt, anthropic_msgs


def _convert_tools_for_anthropic(tools: Optional[list[dict]]) -> list[dict]:
    """Convert OpenAI function-calling tool schemas → Anthropic tool blocks."""
    if not tools:
        return []
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") != "function":
            continue
        fn = t.get("function") or {}
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "description": str(fn.get("description") or ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _extract_anthropic_response(body: dict) -> tuple[str, list[dict]]:
    """Pull out plain text + tool_calls from an Anthropic response body."""
    content = body.get("content") or []
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type == "text":
            t = block.get("text")
            if isinstance(t, str):
                text_parts.append(t)
        elif block_type == "tool_use":
            tool_calls.append({
                "name": str(block.get("name") or ""),
                "arguments": block.get("input") if isinstance(block.get("input"), dict) else {},
            })

    return "".join(text_parts), tool_calls


class AnthropicProvider(ModelProvider):
    """Calls Anthropic's native Messages API.

    Args:
        api_key: Anthropic API key (`sk-ant-...`).
        model_name: Model id (e.g. `claude-3-5-sonnet-latest`,
            `claude-3-5-haiku-latest`, `claude-opus-4-1-20250805`).
        base_url: API base. Defaults to the public endpoint.
        timeout_sec: Per-request timeout.
        api_version: `anthropic-version` header. Defaults to a recent
            stable version.
    """

    __slots__ = ("api_key", "model_name", "base_url", "timeout_sec", "api_version")

    def __init__(
        self,
        api_key: str,
        model_name: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_sec: int = 120,
        api_version: str = _DEFAULT_API_VERSION,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = int(timeout_sec) if timeout_sec else 120
        self.api_version = api_version

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
    ) -> ModelResponse:
        import urllib.error
        import urllib.request

        system_prompt, anthro_messages = _convert_messages(messages)
        if not anthro_messages:
            # Anthropic requires at least one user message; surface a clear
            # error rather than letting the API 400.
            return ModelResponse(
                text="",
                tool_calls=[],
                emotion="neutral",
                raw_output="",
                error="InvalidInput: anthropic requires at least one user message",
            )

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": anthro_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        anthro_tools = _convert_tools_for_anthropic(tools)
        if anthro_tools:
            payload["tools"] = anthro_tools

        url = f"{self.base_url}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
        }

        try:
            t0 = time.monotonic()
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            log(
                "model",
                "anthropic.request",
                base_url=self.base_url,
                model=self.model_name,
                tools=bool(anthro_tools),
                elapsed_ms=f"{(time.monotonic()-t0)*1000:.1f}",
            )

            text, tool_calls = _extract_anthropic_response(body)
            return ModelResponse(
                text=text,
                tool_calls=tool_calls,
                emotion="neutral",
                raw_output=json.dumps(body, ensure_ascii=False),
                error=None,
            )
        except urllib.error.URLError as exc:
            logger.error("Anthropic API call failed: %s", exc)
            return ModelResponse(
                text=f"云端模型调用失败: {exc}",
                tool_calls=[],
                emotion="sad",
                raw_output="",
                error=f"URLError: {exc}",
            )
        except Exception as exc:
            logger.error("Anthropic API unexpected error: %s", exc)
            return ModelResponse(
                text=f"云端模型调用失败: {exc}",
                tool_calls=[],
                emotion="sad",
                raw_output="",
                error=f"{type(exc).__name__}: {exc}",
            )

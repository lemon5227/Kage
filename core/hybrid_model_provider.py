"""HybridModelProvider — try local first, fall back to cloud on failure.

Goals:
  * Pure local stays the default (cloud is only consulted if explicitly enabled
    AND a cloud API key is configured).
  * Cheap when local succeeds: no extra work, no extra allocations beyond the
    wrapping ModelResponse.
  * Honest failure semantics: if both providers fail, the local error is
    surfaced (so users know the local stack is down, not a network issue).
  * Optional escalation hint: when the user's input contains any of a
    configurable list of "complexity" keywords (e.g. "深度分析"), skip local
    and go to cloud directly. This is opt-in — by default the keyword list
    is empty.

The class deliberately does *not* implement timeouts itself; the underlying
OpenAICompatibleProvider already honours `timeout_sec`. We rely on the local
provider returning quickly and signalling failure via ModelResponse.error.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.model_provider import ModelProvider, ModelResponse

logger = logging.getLogger(__name__)


def _last_user_text(messages: list[dict]) -> str:
    """Return the last user-role message content as plain string."""
    if not messages:
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        # OpenAI multi-part content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return ""
    return ""


class HybridModelProvider(ModelProvider):
    """Wraps a local provider and an optional cloud provider with simple
    fallback rules.

    Args:
        local: The primary (local) provider. Always called first in the
            normal path. Required.
        cloud: The fallback provider. If None, the hybrid degrades to a
            transparent passthrough of the local provider — the runtime
            behaves exactly as if hybrid mode were disabled.
        escalate_keywords: Tuple of substrings that, when found in the
            last user message, force a direct cloud call (skipping local).
            Empty by default. Stored as a frozen tuple to avoid mutation
            and to keep `keyword in text` fast.
    """

    __slots__ = ("_local", "_cloud", "_escalate_keywords")

    def __init__(
        self,
        local: ModelProvider,
        cloud: Optional[ModelProvider] = None,
        escalate_keywords: tuple[str, ...] = (),
    ):
        if local is None:
            raise ValueError("HybridModelProvider requires a local provider")
        self._local = local
        self._cloud = cloud
        # Coerce + freeze for cheap repeated `any(k in text ...)` checks.
        self._escalate_keywords = tuple(
            str(k).strip() for k in (escalate_keywords or ()) if str(k).strip()
        )

    @property
    def has_cloud(self) -> bool:
        return self._cloud is not None

    @property
    def escalate_keywords(self) -> tuple[str, ...]:
        return self._escalate_keywords

    def _should_escalate(self, messages: list[dict]) -> bool:
        if not self._escalate_keywords or self._cloud is None:
            return False
        text = _last_user_text(messages)
        if not text:
            return False
        return any(kw in text for kw in self._escalate_keywords)

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
    ) -> ModelResponse:
        # Pre-route: if the user signalled high-complexity intent and we have
        # a cloud provider, skip local entirely.
        if self._should_escalate(messages):
            logger.info("hybrid: escalating to cloud (keyword match)")
            return self._cloud.generate(  # type: ignore[union-attr]
                messages, tools=tools, max_tokens=max_tokens, temperature=temperature,
            )

        local_resp = self._local.generate(
            messages, tools=tools, max_tokens=max_tokens, temperature=temperature,
        )

        # Happy path: local succeeded.
        if local_resp.error is None:
            return local_resp

        # Local failed AND no cloud configured → return the local response so
        # the caller still sees a meaningful "本地调用失败" message.
        if self._cloud is None:
            logger.warning(
                "hybrid: local failed (%s); cloud not configured, surfacing local error",
                local_resp.error,
            )
            return local_resp

        # Local failed → try cloud. If cloud also fails, prefer surfacing the
        # local error (it tells the user their local stack is offline; the
        # cloud error is a downstream symptom).
        logger.info("hybrid: local failed (%s) → cloud fallback", local_resp.error)
        cloud_resp = self._cloud.generate(
            messages, tools=tools, max_tokens=max_tokens, temperature=temperature,
        )
        if cloud_resp.error is not None:
            logger.warning(
                "hybrid: cloud also failed (%s); returning local error to caller",
                cloud_resp.error,
            )
            # Compose a single error message so caller sees both.
            return ModelResponse(
                text=local_resp.text,
                tool_calls=[],
                emotion="sad",
                raw_output="",
                error=f"local:{local_resp.error}; cloud:{cloud_resp.error}",
            )
        return cloud_resp

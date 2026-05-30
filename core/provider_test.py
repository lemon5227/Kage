"""Provider connection probe.

Lets a user verify their cloud-LLM credentials are working **before**
they rely on the hybrid fallback in production. The probe issues a
single tiny `generate()` call (1 token) and reports success / latency
or an actionable error.

Design notes:
  * The probe is provider-class-agnostic: it builds the same provider
    objects the broker would, then calls `generate()` once.
  * No retries, no exponential backoff — a connection test should be
    fast and deterministic. If it fails, the user likely needs to fix
    their key or network, not retry.
  * Returns a plain dict suitable for direct JSON serialisation.
  * **Never echoes the API key back** in the result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from core.anthropic_provider import AnthropicProvider
from core.model_provider import ModelProvider, ModelResponse, OpenAICompatibleProvider


# Short, neutral probe message — won't trip moderation, won't stress the model.
_PROBE_MESSAGE = "Reply with the single word: ok"
_PROBE_MAX_TOKENS = 4
_PROBE_TIMEOUT_SEC = 10


@dataclass
class ProviderTestResult:
    ok: bool
    provider_type: str
    model: str
    latency_ms: float
    error: Optional[str] = None
    text_sample: str = ""

    def to_dict(self) -> dict:
        # Explicit dict so we never accidentally include sensitive fields.
        return {
            "ok": bool(self.ok),
            "provider_type": str(self.provider_type),
            "model": str(self.model),
            "latency_ms": float(self.latency_ms),
            "error": self.error,
            "text_sample": str(self.text_sample)[:80],
        }


def _make_probe_provider(
    provider_type: str,
    api_key: str,
    model_name: str = "",
    base_url: str = "",
) -> tuple[ModelProvider, str, str]:
    """Build the provider that would be used at runtime, with probe-friendly
    defaults filled in for missing fields.

    Returns (provider, resolved_model_name, resolved_base_url) so the caller
    can include them in the test result.
    """
    ptype = (provider_type or "openai").strip().lower()
    if ptype == "anthropic":
        model = model_name.strip() or "claude-3-5-haiku-latest"
        base = base_url.strip() or "https://api.anthropic.com/v1"
        provider: ModelProvider = AnthropicProvider(
            api_key=api_key,
            model_name=model,
            base_url=base,
            timeout_sec=_PROBE_TIMEOUT_SEC,
        )
    else:
        # Default to OpenAI-compatible, which also covers DeepSeek / Moonshot
        # / Together / local llama-server style endpoints.
        model = model_name.strip() or "gpt-4o-mini"
        base = base_url.strip() or "https://api.openai.com/v1"
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            model_name=model,
            base_url=base,
            timeout_sec=_PROBE_TIMEOUT_SEC,
        )
        ptype = "openai"
    return provider, model, base


def probe_provider(
    provider_type: str,
    api_key: str,
    model_name: str = "",
    base_url: str = "",
) -> ProviderTestResult:
    """Probe a single provider.

    Returns a `ProviderTestResult` describing the outcome. On failure,
    `error` contains a short explanation derived from the underlying
    `ModelResponse.error`.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return ProviderTestResult(
            ok=False,
            provider_type=provider_type or "openai",
            model=model_name or "",
            latency_ms=0.0,
            error="MissingApiKey: no API key configured",
        )

    provider, resolved_model, _resolved_base = _make_probe_provider(
        provider_type=provider_type,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
    )

    t0 = time.monotonic()
    response: ModelResponse = provider.generate(
        messages=[{"role": "user", "content": _PROBE_MESSAGE}],
        max_tokens=_PROBE_MAX_TOKENS,
        temperature=0.0,
    )
    elapsed_ms = (time.monotonic() - t0) * 1000

    return ProviderTestResult(
        ok=response.error is None,
        provider_type=(provider_type or "openai").strip().lower() or "openai",
        model=resolved_model,
        latency_ms=elapsed_ms,
        error=response.error,
        text_sample=str(response.text or "")[:80],
    )

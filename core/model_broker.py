from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.anthropic_provider import AnthropicProvider
from core.hybrid_model_provider import HybridModelProvider
from core.model_provider import ModelProvider, OpenAICompatibleProvider


def _make_openai_compatible_provider(cfg: dict[str, Any] | None) -> OpenAICompatibleProvider:
    config = dict(cfg or {})
    return OpenAICompatibleProvider(
        api_key=str(config.get("api_key") or "local"),
        model_name=str(config.get("model_name") or "local-model"),
        base_url=str(config.get("base_url") or "http://127.0.0.1:8080/v1"),
        timeout_sec=int(config.get("timeout_sec") or 120),
    )


def _make_anthropic_provider(cfg: dict[str, Any] | None) -> AnthropicProvider:
    config = dict(cfg or {})
    return AnthropicProvider(
        api_key=str(config.get("api_key") or ""),
        model_name=str(config.get("model_name") or "claude-3-5-haiku-latest"),
        base_url=str(config.get("base_url") or "https://api.anthropic.com/v1"),
        timeout_sec=int(config.get("timeout_sec") or 120),
    )


def _make_cloud_provider(cfg: dict[str, Any] | None) -> ModelProvider:
    """Pick the right provider class based on `provider_type`.

    Defaults to `openai` (which also covers OpenAI-compatible endpoints
    like Together, Groq, Moonshot, DeepSeek, local llama-server).
    """
    config = dict(cfg or {})
    ptype = str(config.get("provider_type") or "openai").strip().lower()
    if ptype == "anthropic":
        return _make_anthropic_provider(config)
    return _make_openai_compatible_provider(config)


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    mode: str
    provider: ModelProvider


class ModelBroker:
    """Own provider roles without forcing scheduling complexity up-front.

    When `model.hybrid.enabled` is true AND a cloud API key is configured,
    the broker wraps each role's provider in a :class:`HybridModelProvider`
    so failures fall back to the cloud automatically. Otherwise the broker
    behaves exactly as before — pure local by default.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = dict(config or {})
        self._profiles = self._build_profiles(cfg)

    @staticmethod
    def _build_profiles(config: dict[str, Any]) -> dict[str, ProviderProfile]:
        model_cfg = dict(config.get("model") or {})
        local_runtime = dict(model_cfg.get("local_runtime") or {})
        cloud_cfg = dict(model_cfg.get("cloud_api") or {})
        broker_cfg = dict(model_cfg.get("broker") or {})
        hybrid_cfg = dict(model_cfg.get("hybrid") or {})

        local_provider_cfg = {
            "api_key": "local",
            "model_name": str(local_runtime.get("model_name") or "local-model"),
            "base_url": f"http://{local_runtime.get('host') or '127.0.0.1'}:{int(local_runtime.get('port') or 8080)}/v1",
            "timeout_sec": int(local_runtime.get("timeout_sec") or 120),
        }
        cloud_api_key = str(cloud_cfg.get("api_key") or "").strip()
        cloud_provider_type = str(cloud_cfg.get("provider_type") or "openai").strip().lower()
        # Default model name depends on provider — Anthropic defaults to a
        # cheap fast Claude model unless the user has named their own.
        default_cloud_model = "claude-3-5-haiku-latest" if cloud_provider_type == "anthropic" else "gpt-4o-mini"
        default_cloud_base_url = (
            "https://api.anthropic.com/v1" if cloud_provider_type == "anthropic"
            else "https://api.openai.com/v1"
        )
        cloud_provider_cfg = {
            "provider_type": cloud_provider_type,
            "api_key": cloud_api_key,
            "model_name": str(cloud_cfg.get("model_name") or default_cloud_model),
            "base_url": str(cloud_cfg.get("base_url") or default_cloud_base_url),
            "timeout_sec": int(cloud_cfg.get("timeout_sec") or 120),
        }

        # Hybrid mode is active only if (a) the user opted in via config and
        # (b) a cloud API key is actually configured. Without the key we can
        # not call the cloud anyway — degrade gracefully to local-only.
        hybrid_enabled = bool(hybrid_cfg.get("enabled")) and bool(cloud_api_key)
        escalate_keywords_raw = hybrid_cfg.get("escalate_keywords") or ()
        if isinstance(escalate_keywords_raw, str):
            escalate_keywords_raw = [escalate_keywords_raw]
        escalate_keywords = tuple(
            str(k).strip() for k in escalate_keywords_raw if str(k).strip()
        )

        def resolve_mode(role: str, default: str) -> str:
            mode = str(broker_cfg.get(role) or default).strip().lower()
            if mode not in ("local", "cloud"):
                return default
            return mode

        def make_local() -> ModelProvider:
            return _make_openai_compatible_provider(local_provider_cfg)

        def make_cloud() -> ModelProvider | None:
            if not cloud_api_key:
                return None
            return _make_cloud_provider(cloud_provider_cfg)

        def resolve_profile(role: str, default: str) -> ProviderProfile:
            mode = resolve_mode(role, default)

            if hybrid_enabled:
                # In hybrid mode every role gets a (local + cloud) pair.
                # The local stays primary; cloud is the fallback.
                wrapped = HybridModelProvider(
                    local=make_local(),
                    cloud=make_cloud(),
                    escalate_keywords=escalate_keywords,
                )
                return ProviderProfile(name=role, mode="hybrid", provider=wrapped)

            # Non-hybrid path (pure local OR explicit cloud per role).
            use_cloud = mode == "cloud" and cloud_api_key
            if use_cloud:
                actual_mode = "cloud"
                provider = _make_cloud_provider(cloud_provider_cfg)
            else:
                actual_mode = "local"
                provider = _make_openai_compatible_provider(local_provider_cfg)
            return ProviderProfile(
                name=role,
                mode=actual_mode,
                provider=provider,
            )

        return {
            "routing": resolve_profile("routing_provider", "local"),
            "realtime": resolve_profile("realtime_provider", "local"),
            "background": resolve_profile("background_provider", "local"),
            "fallback_cloud": resolve_profile("fallback_provider", "cloud"),
        }

    def profile(self, name: str) -> ProviderProfile:
        return self._profiles[name]

    @property
    def routing_provider(self) -> ModelProvider:
        return self.profile("routing").provider

    @property
    def realtime_provider(self) -> ModelProvider:
        return self.profile("realtime").provider

    @property
    def background_provider(self) -> ModelProvider:
        return self.profile("background").provider

    @property
    def fallback_provider(self) -> ModelProvider:
        return self.profile("fallback_cloud").provider

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.model_provider import ModelProvider, OpenAICompatibleProvider


def _make_openai_compatible_provider(cfg: dict[str, Any] | None) -> OpenAICompatibleProvider:
    config = dict(cfg or {})
    return OpenAICompatibleProvider(
        api_key=str(config.get("api_key") or "local"),
        model_name=str(config.get("model_name") or "local-model"),
        base_url=str(config.get("base_url") or "http://127.0.0.1:8080/v1"),
        timeout_sec=int(config.get("timeout_sec") or 120),
    )


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    mode: str
    provider: ModelProvider


class ModelBroker:
    """Own provider roles without forcing scheduling complexity up-front."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = dict(config or {})
        self._profiles = self._build_profiles(cfg)

    @staticmethod
    def _build_profiles(config: dict[str, Any]) -> dict[str, ProviderProfile]:
        model_cfg = dict(config.get("model") or {})
        local_runtime = dict(model_cfg.get("local_runtime") or {})
        cloud_cfg = dict(model_cfg.get("cloud_api") or {})
        broker_cfg = dict(model_cfg.get("broker") or {})

        local_provider_cfg = {
            "api_key": "local",
            "model_name": str(local_runtime.get("model_name") or "local-model"),
            "base_url": f"http://{local_runtime.get('host') or '127.0.0.1'}:{int(local_runtime.get('port') or 8080)}/v1",
            "timeout_sec": int(local_runtime.get("timeout_sec") or 120),
        }
        cloud_provider_cfg = {
            "api_key": str(cloud_cfg.get("api_key") or "").strip(),
            "model_name": str(cloud_cfg.get("model_name") or "gpt-4o-mini"),
            "base_url": str(cloud_cfg.get("base_url") or "https://api.openai.com/v1"),
            "timeout_sec": int(cloud_cfg.get("timeout_sec") or 120),
        }

        def resolve_mode(role: str, default: str) -> str:
            mode = str(broker_cfg.get(role) or default).strip().lower()
            if mode not in ("local", "cloud"):
                return default
            return mode

        def resolve_profile(role: str, default: str) -> ProviderProfile:
            mode = resolve_mode(role, default)
            provider_cfg = cloud_provider_cfg if mode == "cloud" and cloud_provider_cfg["api_key"] else local_provider_cfg
            actual_mode = "cloud" if provider_cfg is cloud_provider_cfg else "local"
            return ProviderProfile(
                name=role,
                mode=actual_mode,
                provider=_make_openai_compatible_provider(provider_cfg),
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

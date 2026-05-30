"""Tests for the provider-connection probe + live broker reload.

Two coupled features:
  1. `core.provider_test.probe_provider()` builds the right provider class
     and issues a single tiny ping. We test it with stub providers (no
     real network) so the probe path is exercised deterministically.
  2. `KageServer.reload_model_broker()` swaps every cached provider
     reference, so a settings change applies without a restart.

The settings API endpoint `/api/settings/test_provider` is also covered
end-to-end with a TestClient + a mocked provider class.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from core.anthropic_provider import AnthropicProvider
from core.model_provider import ModelProvider, ModelResponse, OpenAICompatibleProvider
from core.provider_test import (
    ProviderTestResult,
    _make_probe_provider,
    probe_provider,
)


# ---------------------------------------------------------------------------
# Stub provider that returns whatever we queue. We patch the broker's
# constructors so no real HTTP happens.
# ---------------------------------------------------------------------------

class _ScriptedProvider(ModelProvider):
    def __init__(self, response: ModelResponse, label: str = ""):
        self.response = response
        self.label = label
        self.calls = 0
        self.last_messages = None

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.calls += 1
        self.last_messages = messages
        return self.response


def _ok_response(text: str = "ok") -> ModelResponse:
    return ModelResponse(text=text, error=None)


def _err_response(error: str = "URLError: refused") -> ModelResponse:
    return ModelResponse(text=f"调用失败: {error}", error=error)


# ---------------------------------------------------------------------------
# 1. _make_probe_provider — type dispatch + default fill-in
# ---------------------------------------------------------------------------

class TestMakeProbeProvider:
    def test_anthropic_dispatch(self):
        provider, model, base = _make_probe_provider(
            provider_type="anthropic",
            api_key="sk-ant-test",
        )
        assert isinstance(provider, AnthropicProvider)
        assert "claude" in model.lower()
        assert "anthropic" in base

    def test_openai_dispatch(self):
        provider, model, base = _make_probe_provider(
            provider_type="openai",
            api_key="sk-test",
        )
        assert isinstance(provider, OpenAICompatibleProvider)
        assert model == "gpt-4o-mini"
        assert "openai.com" in base

    def test_unknown_type_falls_back_to_openai(self):
        provider, _, _ = _make_probe_provider(
            provider_type="unknown_vendor",
            api_key="sk-test",
        )
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_explicit_overrides_preserved(self):
        provider, model, base = _make_probe_provider(
            provider_type="openai",
            api_key="sk",
            model_name="custom-model-v2",
            base_url="https://api.deepseek.com/v1",
        )
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.model_name == "custom-model-v2"
        assert provider.base_url == "https://api.deepseek.com/v1"
        assert model == "custom-model-v2"
        assert base == "https://api.deepseek.com/v1"


# ---------------------------------------------------------------------------
# 2. test_provider() — happy path, error path, missing key
# ---------------------------------------------------------------------------

class TestProviderProbeFunction:
    def test_missing_key_short_circuits(self):
        result = probe_provider(provider_type="openai", api_key="")
        assert result.ok is False
        assert "MissingApiKey" in (result.error or "")
        assert result.latency_ms == 0.0

    def test_whitespace_key_treated_as_missing(self):
        result = probe_provider(provider_type="anthropic", api_key="   ")
        assert result.ok is False
        assert "MissingApiKey" in (result.error or "")

    def test_successful_probe_returns_ok(self):
        # Patch the OpenAI-compatible class so its generate() returns a stub
        # success response without making an HTTP call.
        stub = _ScriptedProvider(_ok_response("ok"))
        with patch("core.provider_test.OpenAICompatibleProvider", return_value=stub):
            result = probe_provider(provider_type="openai", api_key="sk-test")

        assert result.ok is True
        assert result.error is None
        assert result.text_sample == "ok"
        assert result.provider_type == "openai"
        assert stub.calls == 1
        # The probe message should be a single user message.
        assert stub.last_messages[0]["role"] == "user"
        assert "ok" in stub.last_messages[0]["content"].lower()

    def test_failed_probe_surfaces_error(self):
        stub = _ScriptedProvider(_err_response("URLError: 401 Unauthorized"))
        with patch("core.provider_test.OpenAICompatibleProvider", return_value=stub):
            result = probe_provider(provider_type="openai", api_key="sk-bad")

        assert result.ok is False
        assert "401" in (result.error or "") or "URLError" in (result.error or "")
        assert stub.calls == 1

    def test_anthropic_dispatch_in_probe(self):
        stub = _ScriptedProvider(_ok_response("ok"))
        with patch("core.provider_test.AnthropicProvider", return_value=stub):
            result = probe_provider(provider_type="anthropic", api_key="sk-ant-test")
        assert result.ok is True
        assert result.provider_type == "anthropic"
        assert "claude" in result.model.lower()

    def test_result_to_dict_strips_secrets(self):
        result = ProviderTestResult(
            ok=True,
            provider_type="anthropic",
            model="claude-3-5",
            latency_ms=42.5,
            text_sample="ok",
        )
        d = result.to_dict()
        # to_dict must not contain api_key / authorization / any secret-ish keys
        assert "api_key" not in d
        assert "authorization" not in d
        assert d["ok"] is True
        assert d["latency_ms"] == 42.5

    def test_text_sample_truncated(self):
        long_text = "x" * 500
        stub = _ScriptedProvider(_ok_response(long_text))
        with patch("core.provider_test.OpenAICompatibleProvider", return_value=stub):
            result = probe_provider(provider_type="openai", api_key="sk-test")
        # to_dict caps text_sample at 80 chars
        assert len(result.to_dict()["text_sample"]) <= 80


# ---------------------------------------------------------------------------
# 3. /api/settings/test_provider endpoint
# ---------------------------------------------------------------------------

class TestProviderTestEndpoint:
    def _make_client(self, monkeypatch, tmp_path):
        from core import server as srv
        monkeypatch.setattr(srv, "_get_user_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            srv, "_get_user_config_path",
            lambda: str(tmp_path / "settings.json"),
        )
        from fastapi.testclient import TestClient
        return TestClient(srv.app)

    def test_explicit_key_probed(self, monkeypatch, tmp_path):
        client = self._make_client(monkeypatch, tmp_path)
        stub = _ScriptedProvider(_ok_response("ok"))
        with patch("core.provider_test.OpenAICompatibleProvider", return_value=stub):
            resp = client.post("/api/settings/test_provider", json={
                "provider_type": "openai",
                "api_key": "sk-typed-by-user",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "sk-typed-by-user" not in json.dumps(body)
        assert stub.calls == 1

    def test_use_stored_pulls_saved_key(self, monkeypatch, tmp_path):
        """When use_stored=True, the probe must pick up the API key from the
        saved settings (not from the request body)."""
        client = self._make_client(monkeypatch, tmp_path)

        # Persist a key via the existing hybrid endpoint
        client.post("/api/settings/hybrid", json={
            "enabled": True,
            "cloud_provider_type": "anthropic",
            "cloud_api_key": "sk-ant-stored",
            "cloud_model_name": "claude-3-5-sonnet-latest",
        })

        stub = _ScriptedProvider(_ok_response("ok"))
        with patch("core.provider_test.AnthropicProvider", return_value=stub):
            resp = client.post("/api/settings/test_provider", json={
                "use_stored": True,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["provider_type"] == "anthropic"
        # Stored model should be reflected in the result
        assert body["model"] == "claude-3-5-sonnet-latest"
        # Raw stored key never returned
        assert "sk-ant-stored" not in json.dumps(body)

    def test_use_env_key_probed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env-probe")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = self._make_client(monkeypatch, tmp_path)

        stub = _ScriptedProvider(_ok_response("ok"))
        with patch("core.provider_test.AnthropicProvider", return_value=stub):
            resp = client.post("/api/settings/test_provider", json={
                "use_env_key": "anthropic",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "sk-ant-from-env-probe" not in json.dumps(body)

    def test_invalid_payload_returns_error(self, monkeypatch, tmp_path):
        client = self._make_client(monkeypatch, tmp_path)
        resp = client.post("/api/settings/test_provider", json="not a dict")
        # Either a 200 with ok=false, or a 422 validation error — both
        # acceptable as long as we don't 5xx.
        assert resp.status_code < 500


# ---------------------------------------------------------------------------
# 4. KageServer.reload_model_broker — swap providers without restart
# ---------------------------------------------------------------------------

class _FakeAgenticLoop:
    """Minimal stand-in for AgenticLoop with just the .model attribute the
    reload path updates."""

    def __init__(self, model):
        self.model = model


def _build_partial_kage_server(initial_config: dict):
    """Build a KageServer instance with __init__ bypassed, populated only
    with the attributes reload_model_broker reads / writes."""
    from core.model_broker import ModelBroker
    from core.server import KageServer

    server = object.__new__(KageServer)
    broker = ModelBroker(initial_config)
    server.model_broker = broker
    server.routing_model_provider = broker.routing_provider
    server.realtime_model_provider = broker.realtime_provider
    server.background_model_provider = broker.background_provider
    server.model_provider = server.background_model_provider
    server.fallback_model_provider = broker.fallback_provider
    server.agentic_loop = _FakeAgenticLoop(server.background_model_provider)
    return server


class TestReloadModelBroker:
    def test_reload_picks_up_config_change(self, monkeypatch, tmp_path):
        from core import server as srv

        # Initial: pure local
        initial_cfg = {
            "model": {
                "broker": {"fallback_provider": "cloud"},
                "cloud_api": {"provider_type": "openai", "api_key": ""},
            }
        }
        kage = _build_partial_kage_server(initial_cfg)
        assert kage.model_broker.profile("realtime").mode == "local"

        # Now point _load_effective_config at a NEW config that turns hybrid on
        new_cfg = {
            "model": {
                "broker": {"fallback_provider": "cloud"},
                "hybrid": {"enabled": True},
                "cloud_api": {
                    "provider_type": "anthropic",
                    "api_key": "sk-ant-new",
                },
            }
        }
        # _load_effective_config also runs _with_config_defaults so we mirror that.
        monkeypatch.setattr(srv, "_load_effective_config",
                            lambda: srv._with_config_defaults(new_cfg))

        kage.reload_model_broker()

        # Every role is now hybrid
        for role in ("routing", "realtime", "background"):
            assert kage.model_broker.profile(role).mode == "hybrid"
        # AgenticLoop's model ref was updated to the new background provider
        assert kage.agentic_loop.model is kage.background_model_provider

    def test_reload_propagates_to_agentic_loop(self, monkeypatch, tmp_path):
        from core import server as srv

        initial_cfg = {"model": {"cloud_api": {"api_key": ""}}}
        kage = _build_partial_kage_server(initial_cfg)
        original_model = kage.agentic_loop.model

        # New config with same shape — broker rebuilds new provider instances.
        monkeypatch.setattr(srv, "_load_effective_config",
                            lambda: srv._with_config_defaults(initial_cfg))
        kage.reload_model_broker()

        # The agentic_loop's model must now be the fresh background provider
        # (a NEW object), not the original one.
        assert kage.agentic_loop.model is kage.background_model_provider
        assert kage.agentic_loop.model is not original_model

    def test_reload_safe_when_no_agentic_loop(self, monkeypatch):
        from core import server as srv
        from core.model_broker import ModelBroker
        from core.server import KageServer

        # Build server without agentic_loop attribute
        kage = object.__new__(KageServer)
        kage.model_broker = ModelBroker({"model": {}})
        kage.routing_model_provider = kage.model_broker.routing_provider
        kage.realtime_model_provider = kage.model_broker.realtime_provider
        kage.background_model_provider = kage.model_broker.background_provider
        kage.model_provider = kage.background_model_provider
        kage.fallback_model_provider = kage.model_broker.fallback_provider
        # NOTE: no kage.agentic_loop attribute

        monkeypatch.setattr(srv, "_load_effective_config",
                            lambda: srv._with_config_defaults({"model": {}}))

        # Must not raise
        kage.reload_model_broker()


# ---------------------------------------------------------------------------
# 5. /api/settings/hybrid auto-reloads after save (when server registered)
# ---------------------------------------------------------------------------

class TestHybridSaveAutoReload:
    def _make_client(self, monkeypatch, tmp_path):
        from core import server as srv
        monkeypatch.setattr(srv, "_get_user_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            srv, "_get_user_config_path",
            lambda: str(tmp_path / "settings.json"),
        )
        from fastapi.testclient import TestClient
        return TestClient(srv.app)

    def test_no_server_registered_returns_skipped(self, monkeypatch, tmp_path):
        """Without an active KageServer (e.g. control-plane mode pre-runtime
        boot) the save endpoint should still succeed with reload=skipped."""
        from core import server as srv
        monkeypatch.setattr(srv, "_get_kage_server", lambda: None)
        client = self._make_client(monkeypatch, tmp_path)

        resp = client.post("/api/settings/hybrid", json={
            "enabled": False,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["reload"] == "skipped"

    def test_server_registered_reload_applied(self, monkeypatch, tmp_path):
        from core import server as srv

        # Inject a partial kage server that supports reload_model_broker
        kage = _build_partial_kage_server({
            "model": {"cloud_api": {"api_key": ""}},
        })
        monkeypatch.setattr(srv, "_get_kage_server", lambda: kage)
        client = self._make_client(monkeypatch, tmp_path)

        resp = client.post("/api/settings/hybrid", json={
            "enabled": True,
            "cloud_provider_type": "anthropic",
            "cloud_api_key": "sk-ant-new",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["reload"] == "applied"
        # Broker actually picked up the new key → role mode flipped to hybrid
        assert kage.model_broker.profile("realtime").mode == "hybrid"

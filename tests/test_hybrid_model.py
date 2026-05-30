"""Tests for hybrid local+cloud LLM mode.

Contract:
  * Pure local default — when hybrid.enabled is False, the broker hands out
    plain local providers and never touches the cloud (preserves privacy).
  * Hybrid enabled but no cloud key — degrades gracefully back to local-only;
    no crashes, no surprise cloud calls.
  * Hybrid enabled + key configured — every model role is wrapped in
    HybridModelProvider with the configured cloud as fallback.
  * Failure semantics — local error → cloud is consulted; both-fail keeps
    the local error visible to the caller (the user's actionable signal).
  * Escalation keywords — pre-route directly to cloud, skipping local, for
    explicit complex requests (opt-in, empty by default).
  * Settings API — POST /api/settings/hybrid persists; GET never echoes the
    raw key back (only a "configured" flag).

All tests run offline; no real network calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from core.hybrid_model_provider import HybridModelProvider, _last_user_text
from core.model_broker import ModelBroker
from core.model_provider import ModelProvider, ModelResponse


# ---------------------------------------------------------------------------
# Stub providers — record calls so we can assert who was called and when
# ---------------------------------------------------------------------------

@dataclass
class _Recorder:
    calls: int = 0
    last_messages: list = None  # type: ignore[assignment]


class _FixedProvider(ModelProvider):
    """Provider that always returns the configured ModelResponse and records
    how many times it was invoked."""

    def __init__(self, response: ModelResponse, label: str = ""):
        self.response = response
        self.label = label
        self.recorder = _Recorder()

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        self.recorder.calls += 1
        self.recorder.last_messages = messages
        return self.response


def _ok_response(text: str = "ok", label: str = "") -> ModelResponse:
    return ModelResponse(text=text, tool_calls=[], emotion="neutral",
                         raw_output=label, error=None)


def _err_response(error_msg: str = "URLError: timeout", label: str = "") -> ModelResponse:
    return ModelResponse(text=f"调用失败: {error_msg}", tool_calls=[], emotion="sad",
                         raw_output=label, error=error_msg)


# ---------------------------------------------------------------------------
# 1. ModelResponse contract
# ---------------------------------------------------------------------------

class TestModelResponseError:
    def test_default_error_is_none(self):
        r = ModelResponse(text="hi")
        assert r.error is None

    def test_error_field_settable(self):
        r = ModelResponse(text="failed", error="URLError: dns")
        assert r.error == "URLError: dns"


# ---------------------------------------------------------------------------
# 2. HybridModelProvider — local-first, no cloud
# ---------------------------------------------------------------------------

class TestHybridLocalSuccess:
    def test_local_success_does_not_call_cloud(self):
        local = _FixedProvider(_ok_response("local-ok", "local"))
        cloud = _FixedProvider(_ok_response("cloud-ok", "cloud"))
        h = HybridModelProvider(local=local, cloud=cloud)

        out = h.generate([{"role": "user", "content": "hi"}])

        assert out.text == "local-ok"
        assert local.recorder.calls == 1
        assert cloud.recorder.calls == 0, "cloud must not be touched on local success"

    def test_local_success_with_no_cloud_configured(self):
        local = _FixedProvider(_ok_response("local-ok"))
        h = HybridModelProvider(local=local, cloud=None)

        out = h.generate([{"role": "user", "content": "hi"}])

        assert out.text == "local-ok"
        assert local.recorder.calls == 1
        assert h.has_cloud is False


# ---------------------------------------------------------------------------
# 3. HybridModelProvider — local fail, cloud fallback
# ---------------------------------------------------------------------------

class TestHybridFallback:
    def test_local_error_falls_back_to_cloud(self):
        local = _FixedProvider(_err_response("URLError: connection refused"))
        cloud = _FixedProvider(_ok_response("cloud-recovered"))
        h = HybridModelProvider(local=local, cloud=cloud)

        out = h.generate([{"role": "user", "content": "hi"}])

        assert local.recorder.calls == 1
        assert cloud.recorder.calls == 1
        assert out.text == "cloud-recovered"
        assert out.error is None

    def test_local_error_no_cloud_returns_local_response(self):
        """When cloud not configured, the local error must be visible to the
        caller — otherwise users won't know their local stack is offline."""
        local = _FixedProvider(_err_response("URLError: refused"))
        h = HybridModelProvider(local=local, cloud=None)

        out = h.generate([{"role": "user", "content": "hi"}])

        assert local.recorder.calls == 1
        assert out.error is not None
        assert "URLError: refused" in out.error

    def test_both_fail_surfaces_composite_error(self):
        local = _FixedProvider(_err_response("URLError: local-down"))
        cloud = _FixedProvider(_err_response("URLError: 401-unauthorised"))
        h = HybridModelProvider(local=local, cloud=cloud)

        out = h.generate([{"role": "user", "content": "hi"}])

        assert local.recorder.calls == 1
        assert cloud.recorder.calls == 1
        assert out.error is not None
        assert "local:" in out.error
        assert "cloud:" in out.error
        assert "local-down" in out.error
        assert "401-unauthorised" in out.error


# ---------------------------------------------------------------------------
# 4. HybridModelProvider — escalation keywords
# ---------------------------------------------------------------------------

class TestHybridEscalation:
    def test_escalation_keyword_skips_local(self):
        local = _FixedProvider(_ok_response("local-cheap"))
        cloud = _FixedProvider(_ok_response("cloud-deep"))
        h = HybridModelProvider(
            local=local,
            cloud=cloud,
            escalate_keywords=("深度分析", "复杂推理"),
        )

        out = h.generate([{"role": "user", "content": "请帮我做深度分析"}])

        assert cloud.recorder.calls == 1
        assert local.recorder.calls == 0, "complexity keyword must skip local"
        assert out.text == "cloud-deep"

    def test_escalation_only_inspects_user_role(self):
        """A keyword only present in a system / assistant message must NOT
        trigger escalation — that would let the persona prompt force cloud."""
        local = _FixedProvider(_ok_response("local-ok"))
        cloud = _FixedProvider(_ok_response("cloud-ok"))
        h = HybridModelProvider(
            local=local, cloud=cloud,
            escalate_keywords=("深度分析",),
        )

        out = h.generate([
            {"role": "system", "content": "你需要做深度分析"},
            {"role": "user", "content": "你好"},
        ])

        assert local.recorder.calls == 1
        assert cloud.recorder.calls == 0
        assert out.text == "local-ok"

    def test_escalation_inspects_last_user_only(self):
        local = _FixedProvider(_ok_response("local-ok"))
        cloud = _FixedProvider(_ok_response("cloud-deep"))
        h = HybridModelProvider(
            local=local, cloud=cloud,
            escalate_keywords=("深度分析",),
        )

        # First user message has the keyword, but last user does not — must
        # NOT escalate; only the most recent user input matters.
        out = h.generate([
            {"role": "user", "content": "之前我提过深度分析"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "现在只是问候"},
        ])

        assert local.recorder.calls == 1
        assert cloud.recorder.calls == 0
        assert out.text == "local-ok"

    def test_escalation_with_no_cloud_falls_through_to_local(self):
        local = _FixedProvider(_ok_response("local-ok"))
        h = HybridModelProvider(
            local=local, cloud=None,
            escalate_keywords=("深度分析",),
        )

        out = h.generate([{"role": "user", "content": "深度分析这个问题"}])

        assert local.recorder.calls == 1
        assert out.text == "local-ok"

    def test_empty_keywords_list_never_escalates(self):
        local = _FixedProvider(_ok_response("local-ok"))
        cloud = _FixedProvider(_ok_response("cloud-deep"))
        h = HybridModelProvider(local=local, cloud=cloud, escalate_keywords=())

        h.generate([{"role": "user", "content": "深度分析"}])

        assert local.recorder.calls == 1
        assert cloud.recorder.calls == 0


# ---------------------------------------------------------------------------
# 5. _last_user_text helper
# ---------------------------------------------------------------------------

class TestLastUserText:
    def test_simple_string_content(self):
        assert _last_user_text([{"role": "user", "content": "hi"}]) == "hi"

    def test_multipart_content(self):
        assert _last_user_text([
            {"role": "user", "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]},
        ]) == "firstsecond"

    def test_skips_assistant_messages(self):
        msgs = [
            {"role": "user", "content": "first user"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second user"},
        ]
        assert _last_user_text(msgs) == "second user"

    def test_no_user_messages(self):
        assert _last_user_text([{"role": "system", "content": "x"}]) == ""

    def test_empty(self):
        assert _last_user_text([]) == ""


# ---------------------------------------------------------------------------
# 6. ModelBroker — wires hybrid only when both flags allow
# ---------------------------------------------------------------------------

class TestModelBrokerHybridGating:
    def test_pure_local_default_when_hybrid_disabled(self):
        """No hybrid section at all → every profile is plain local."""
        broker = ModelBroker({"model": {}})
        for role in ("routing", "realtime", "background"):
            assert broker.profile(role).mode == "local"
            assert not isinstance(broker.profile(role).provider, HybridModelProvider)

    def test_hybrid_enabled_without_api_key_stays_local(self):
        """Opting in but forgetting to set the key must NOT enable hybrid;
        otherwise every call would just hit a 401 cloud and feel broken."""
        broker = ModelBroker({
            "model": {
                "hybrid": {"enabled": True},
                "cloud_api": {"api_key": ""},
            }
        })
        for role in ("routing", "realtime", "background"):
            assert broker.profile(role).mode == "local", \
                f"role {role} should be local without api_key, got {broker.profile(role).mode}"

    def test_hybrid_active_when_enabled_and_key_present(self):
        broker = ModelBroker({
            "model": {
                "hybrid": {"enabled": True, "escalate_keywords": ["深度分析"]},
                "cloud_api": {
                    "api_key": "sk-test",
                    "model_name": "gpt-4o-mini",
                    "base_url": "https://api.openai.com/v1",
                },
            }
        })
        for role in ("routing", "realtime", "background"):
            profile = broker.profile(role)
            assert profile.mode == "hybrid", f"role {role} mode={profile.mode}"
            assert isinstance(profile.provider, HybridModelProvider)
            assert profile.provider.has_cloud is True
            assert profile.provider.escalate_keywords == ("深度分析",)

    def test_hybrid_escalate_keywords_string_normalized(self):
        """User config may store a comma-separated string by mistake; the
        broker should still tolerate it."""
        broker = ModelBroker({
            "model": {
                "hybrid": {"enabled": True, "escalate_keywords": "深度分析"},
                "cloud_api": {"api_key": "sk-test"},
            }
        })
        kw = broker.profile("realtime").provider.escalate_keywords
        assert kw == ("深度分析",)


# ---------------------------------------------------------------------------
# 7. Settings API — round-trip + secret hygiene
# ---------------------------------------------------------------------------

class TestHybridSettingsApi:
    """The /api/settings/hybrid endpoints persist via _save_user_config_patch.
    Tests use the FastAPI TestClient + a temporary user-config dir."""

    def _make_client(self, monkeypatch, tmp_path):
        # Redirect user-config dir to a temp path so we don't touch the real one.
        from core import server as srv
        monkeypatch.setattr(srv, "_get_user_dir", lambda: str(tmp_path))
        # Also redirect get_user_config_path to within tmp
        monkeypatch.setattr(
            srv, "_get_user_config_path",
            lambda: str(tmp_path / "settings.json"),
        )
        from fastapi.testclient import TestClient
        return TestClient(srv.app)

    def test_post_persists_and_get_returns_non_secret_fields(self, monkeypatch, tmp_path):
        client = self._make_client(monkeypatch, tmp_path)

        resp = client.post("/api/settings/hybrid", json={
            "enabled": True,
            "escalate_keywords": "深度分析,复杂推理",
            "cloud_api_key": "sk-secret-xyz",
            "cloud_model_name": "gpt-4o",
            "cloud_base_url": "https://api.openai.com/v1",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        # GET should not echo the API key back.
        resp = client.get("/api/settings/hybrid")
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["enabled"] is True
        assert cfg["escalate_keywords"] == ["深度分析", "复杂推理"]
        assert cfg["cloud_model_name"] == "gpt-4o"
        assert cfg["cloud_base_url"] == "https://api.openai.com/v1"
        assert cfg["cloud_key_configured"] is True
        assert "cloud_api_key" not in cfg
        assert "sk-secret-xyz" not in json.dumps(cfg)

    def test_empty_key_does_not_overwrite_existing(self, monkeypatch, tmp_path):
        client = self._make_client(monkeypatch, tmp_path)

        # First save sets the key.
        client.post("/api/settings/hybrid", json={
            "enabled": True,
            "cloud_api_key": "sk-original",
        })
        # Second save without a key — must keep the original.
        client.post("/api/settings/hybrid", json={
            "enabled": True,
            "escalate_keywords": [],
        })
        cfg = client.get("/api/settings/hybrid").json()
        assert cfg["cloud_key_configured"] is True

    def test_disabled_state_persists(self, monkeypatch, tmp_path):
        client = self._make_client(monkeypatch, tmp_path)
        client.post("/api/settings/hybrid", json={"enabled": False})
        cfg = client.get("/api/settings/hybrid").json()
        assert cfg["enabled"] is False

    def test_invalid_payload_returns_error(self, monkeypatch, tmp_path):
        client = self._make_client(monkeypatch, tmp_path)
        # A non-object body — the handler should reject it without crashing.
        resp = client.post("/api/settings/hybrid", json="not-a-dict")
        # FastAPI itself may 422 the type before the handler even runs; either
        # way the response should not be 5xx.
        assert resp.status_code < 500

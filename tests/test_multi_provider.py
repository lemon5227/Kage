"""Tests for multi-provider support + env-based credential detection.

Covers:
  * AnthropicProvider message-format conversion (system separated, role
    alternation enforced, tool block conversion, response extraction).
  * AnthropicProvider error path populates ModelResponse.error.
  * credential_helpers.detect_provider_credentials inspects env only and
    never returns the raw value.
  * credential_helpers.read_provider_credential returns the env value or "".
  * ModelBroker dispatch: provider_type=="anthropic" yields AnthropicProvider.
  * Settings API: GET /providers/detect; POST /hybrid with use_env_key.

No real network or LLM calls; the AnthropicProvider HTTP path is exercised
only at the converter boundaries.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from core.anthropic_provider import (
    AnthropicProvider,
    _convert_messages,
    _convert_tools_for_anthropic,
    _extract_anthropic_response,
)
from core.credential_helpers import (
    detect_provider_credentials,
    read_provider_credential,
)
from core.model_broker import ModelBroker


# ---------------------------------------------------------------------------
# 1. Message conversion: OpenAI → Anthropic
# ---------------------------------------------------------------------------

class TestConvertMessages:
    def test_system_separated_from_messages(self):
        sys_, msgs = _convert_messages([
            {"role": "system", "content": "you are kage"},
            {"role": "user", "content": "hi"},
        ])
        assert sys_ == "you are kage"
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_multiple_system_messages_concatenated(self):
        sys_, msgs = _convert_messages([
            {"role": "system", "content": "rule one"},
            {"role": "system", "content": "rule two"},
            {"role": "user", "content": "hello"},
        ])
        assert "rule one" in sys_
        assert "rule two" in sys_
        assert len(msgs) == 1

    def test_consecutive_user_messages_merged(self):
        """Anthropic requires alternating roles. We merge consecutive
        same-role messages with newline separation rather than failing."""
        _, msgs = _convert_messages([
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ])
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "first" in msgs[0]["content"]
        assert "second" in msgs[0]["content"]

    def test_consecutive_assistant_messages_merged(self):
        _, msgs = _convert_messages([
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "part1"},
            {"role": "assistant", "content": "part2"},
        ])
        # Should have 2 entries: user(q), assistant(part1\npart2)
        assert len(msgs) == 2
        assert msgs[1]["role"] == "assistant"
        assert "part1" in msgs[1]["content"]
        assert "part2" in msgs[1]["content"]

    def test_alternating_dialogue_preserved(self):
        _, msgs = _convert_messages([
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ])
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]

    def test_multipart_content_flattened(self):
        _, msgs = _convert_messages([
            {"role": "user", "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]},
        ])
        assert msgs == [{"role": "user", "content": "firstsecond"}]

    def test_tool_role_messages_skipped(self):
        """Anthropic handles tool results via dedicated content blocks; the
        OpenAI-style 'tool' role is dropped at conversion (the agentic loop
        already inlines tool output as user messages elsewhere)."""
        _, msgs = _convert_messages([
            {"role": "user", "content": "u"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "a"},
        ])
        assert [m["role"] for m in msgs] == ["user", "assistant"]

    def test_empty_content_skipped(self):
        _, msgs = _convert_messages([
            {"role": "user", "content": ""},
            {"role": "user", "content": "hi"},
        ])
        # Empty user message is dropped, only the meaningful one remains
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_no_user_messages_returns_empty(self):
        sys_, msgs = _convert_messages([
            {"role": "system", "content": "only system"},
        ])
        assert sys_ == "only system"
        assert msgs == []


# ---------------------------------------------------------------------------
# 2. Tool conversion
# ---------------------------------------------------------------------------

class TestConvertTools:
    def test_basic_function_to_tool_use(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "search",
                "description": "search the web",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }]
        out = _convert_tools_for_anthropic(tools)
        assert len(out) == 1
        assert out[0]["name"] == "search"
        assert out[0]["description"] == "search the web"
        assert "input_schema" in out[0]
        assert out[0]["input_schema"]["properties"]["query"]["type"] == "string"

    def test_skips_non_function_tools(self):
        tools = [
            {"type": "retrieval"},
            {"type": "function", "function": {"name": "ok", "parameters": {}}},
        ]
        out = _convert_tools_for_anthropic(tools)
        assert len(out) == 1
        assert out[0]["name"] == "ok"

    def test_empty_input(self):
        assert _convert_tools_for_anthropic(None) == []
        assert _convert_tools_for_anthropic([]) == []

    def test_function_without_name_skipped(self):
        out = _convert_tools_for_anthropic([
            {"type": "function", "function": {"description": "no name"}},
        ])
        assert out == []


# ---------------------------------------------------------------------------
# 3. Response extraction
# ---------------------------------------------------------------------------

class TestExtractAnthropicResponse:
    def test_text_only(self):
        text, calls = _extract_anthropic_response({
            "content": [{"type": "text", "text": "hello"}],
        })
        assert text == "hello"
        assert calls == []

    def test_tool_use(self):
        text, calls = _extract_anthropic_response({
            "content": [
                {"type": "text", "text": "calling tool"},
                {"type": "tool_use", "name": "search", "input": {"query": "kage"}},
            ],
        })
        assert text == "calling tool"
        assert calls == [{"name": "search", "arguments": {"query": "kage"}}]

    def test_multiple_text_blocks_concatenated(self):
        text, _ = _extract_anthropic_response({
            "content": [
                {"type": "text", "text": "part1"},
                {"type": "text", "text": "part2"},
            ],
        })
        assert text == "part1part2"

    def test_empty_content(self):
        text, calls = _extract_anthropic_response({"content": []})
        assert text == ""
        assert calls == []


# ---------------------------------------------------------------------------
# 4. AnthropicProvider error paths
# ---------------------------------------------------------------------------

class TestAnthropicProviderErrors:
    def test_no_user_messages_returns_explicit_error(self):
        provider = AnthropicProvider(api_key="sk-ant-test")
        out = provider.generate([{"role": "system", "content": "x"}])
        assert out.error is not None
        assert "InvalidInput" in out.error

    def test_network_error_populates_error_field(self):
        import urllib.error

        def _raise(*_a, **_kw):
            raise urllib.error.URLError("connection refused")

        provider = AnthropicProvider(api_key="sk-ant-test")
        with patch("urllib.request.urlopen", side_effect=_raise):
            out = provider.generate([{"role": "user", "content": "hi"}])

        assert out.error is not None
        assert "URLError" in out.error
        assert out.emotion == "sad"


# ---------------------------------------------------------------------------
# 5. Credential detection
# ---------------------------------------------------------------------------

class TestCredentialDetection:
    def test_no_keys_present(self):
        # Provide an empty env explicitly so test isolation is guaranteed.
        out = detect_provider_credentials(env={})
        for provider, info in out.items():
            assert info["present"] is False
            assert info["source"] == ""

    def test_anthropic_key_detected(self):
        out = detect_provider_credentials(env={"ANTHROPIC_API_KEY": "sk-ant-xyz"})
        assert out["anthropic"]["present"] is True
        assert "Claude Code" in out["anthropic"]["source"]
        assert out["openai"]["present"] is False

    def test_legacy_claude_key_detected(self):
        out = detect_provider_credentials(env={"CLAUDE_API_KEY": "legacy"})
        assert out["anthropic"]["present"] is True
        assert "legacy" in out["anthropic"]["source"].lower()

    def test_openai_key_detected(self):
        out = detect_provider_credentials(env={"OPENAI_API_KEY": "sk-xxx"})
        assert out["openai"]["present"] is True
        assert "OpenAI" in out["openai"]["source"] or "Codex" in out["openai"]["source"]

    def test_multiple_keys_all_reported(self):
        out = detect_provider_credentials(env={
            "ANTHROPIC_API_KEY": "x",
            "OPENAI_API_KEY": "y",
            "DEEPSEEK_API_KEY": "z",
        })
        assert out["anthropic"]["present"] is True
        assert out["openai"]["present"] is True
        assert out["deepseek"]["present"] is True
        assert out["google"]["present"] is False

    def test_whitespace_only_treated_as_absent(self):
        out = detect_provider_credentials(env={"ANTHROPIC_API_KEY": "   "})
        assert out["anthropic"]["present"] is False

    def test_detect_returns_no_raw_keys(self):
        """The dict must never echo the API key value back."""
        out = detect_provider_credentials(env={"ANTHROPIC_API_KEY": "sk-ant-secret-xyz"})
        serialised = json.dumps(out)
        assert "sk-ant-secret-xyz" not in serialised


class TestReadProviderCredential:
    def test_reads_key_from_env(self):
        assert read_provider_credential("anthropic", env={"ANTHROPIC_API_KEY": "sk-ant"}) == "sk-ant"
        assert read_provider_credential("openai", env={"OPENAI_API_KEY": "sk-oa"}) == "sk-oa"

    def test_unknown_provider_returns_empty(self):
        assert read_provider_credential("nonexistent", env={"ANYTHING": "x"}) == ""

    def test_missing_key_returns_empty(self):
        assert read_provider_credential("anthropic", env={}) == ""

    def test_strips_whitespace(self):
        assert read_provider_credential("anthropic", env={"ANTHROPIC_API_KEY": "  sk-ant  "}) == "sk-ant"


# ---------------------------------------------------------------------------
# 6. Broker dispatch by provider_type
# ---------------------------------------------------------------------------

class TestBrokerProviderDispatch:
    def test_anthropic_provider_type_yields_anthropic_class(self):
        broker = ModelBroker({
            "model": {
                "broker": {"fallback_provider": "cloud"},
                "cloud_api": {
                    "provider_type": "anthropic",
                    "api_key": "sk-ant-xyz",
                    "model_name": "claude-3-5-sonnet-latest",
                },
            }
        })
        fallback = broker.profile("fallback_cloud")
        assert fallback.mode == "cloud"
        assert isinstance(fallback.provider, AnthropicProvider)
        assert fallback.provider.model_name == "claude-3-5-sonnet-latest"

    def test_openai_provider_type_yields_openai_class(self):
        from core.model_provider import OpenAICompatibleProvider
        broker = ModelBroker({
            "model": {
                "broker": {"fallback_provider": "cloud"},
                "cloud_api": {
                    "provider_type": "openai",
                    "api_key": "sk-test",
                },
            }
        })
        fallback = broker.profile("fallback_cloud")
        assert isinstance(fallback.provider, OpenAICompatibleProvider)

    def test_unknown_provider_type_falls_back_to_openai(self):
        from core.model_provider import OpenAICompatibleProvider
        broker = ModelBroker({
            "model": {
                "broker": {"fallback_provider": "cloud"},
                "cloud_api": {
                    "provider_type": "unknown_vendor",
                    "api_key": "sk-test",
                },
            }
        })
        fallback = broker.profile("fallback_cloud")
        assert isinstance(fallback.provider, OpenAICompatibleProvider)

    def test_anthropic_with_hybrid_wraps_in_hybrid_provider(self):
        from core.hybrid_model_provider import HybridModelProvider
        broker = ModelBroker({
            "model": {
                "hybrid": {"enabled": True},
                "cloud_api": {
                    "provider_type": "anthropic",
                    "api_key": "sk-ant-xyz",
                },
            }
        })
        # In hybrid mode, every role is wrapped. The cloud half should be
        # an AnthropicProvider.
        for role in ("routing", "realtime", "background"):
            profile = broker.profile(role)
            assert profile.mode == "hybrid"
            assert isinstance(profile.provider, HybridModelProvider)
            # Inspect the wrapped cloud provider via the slot.
            assert isinstance(profile.provider._cloud, AnthropicProvider)

    def test_anthropic_default_model_name_when_unset(self):
        """When the user picks Anthropic but doesn't name a model, the
        broker must default to a sensible Claude model rather than e.g.
        gpt-4o-mini."""
        broker = ModelBroker({
            "model": {
                "broker": {"fallback_provider": "cloud"},
                "cloud_api": {
                    "provider_type": "anthropic",
                    "api_key": "sk-ant-xyz",
                    # model_name intentionally omitted
                },
            }
        })
        fallback = broker.profile("fallback_cloud")
        assert isinstance(fallback.provider, AnthropicProvider)
        assert "claude" in fallback.provider.model_name.lower()


# ---------------------------------------------------------------------------
# 7. Settings API: detect endpoint + use_env_key adoption
# ---------------------------------------------------------------------------

class TestSettingsApiProvidersDetect:
    def _make_client(self, monkeypatch, tmp_path):
        from core import server as srv
        monkeypatch.setattr(srv, "_get_user_dir", lambda: str(tmp_path))
        monkeypatch.setattr(
            srv, "_get_user_config_path",
            lambda: str(tmp_path / "settings.json"),
        )
        from fastapi.testclient import TestClient
        return TestClient(srv.app)

    def test_detect_endpoint_returns_provider_map(self, monkeypatch, tmp_path):
        # Set ANTHROPIC_API_KEY in process env for this test
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-detect")
        client = self._make_client(monkeypatch, tmp_path)

        resp = client.get("/api/settings/providers/detect")
        assert resp.status_code == 200
        body = resp.json()
        assert "providers" in body
        assert body["providers"]["anthropic"]["present"] is True
        # Raw value MUST NOT be echoed back
        assert "sk-ant-test-detect" not in json.dumps(body)

    def test_use_env_key_adopts_existing_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
        # Make sure we don't pollute via OpenAI
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = self._make_client(monkeypatch, tmp_path)

        resp = client.post("/api/settings/hybrid", json={
            "enabled": True,
            "use_env_key": "anthropic",
        })
        assert resp.status_code == 200

        # Verify the key was actually persisted (cloud_key_configured True)
        # and the provider_type was inferred to anthropic.
        cfg = client.get("/api/settings/hybrid").json()
        assert cfg["cloud_key_configured"] is True
        assert cfg["cloud_provider_type"] == "anthropic"
        # Still no raw key in any GET response.
        assert "sk-ant-from-env" not in json.dumps(cfg)

    def test_explicit_key_wins_over_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
        client = self._make_client(monkeypatch, tmp_path)

        # Explicit key overrides — even though use_env_key was passed.
        resp = client.post("/api/settings/hybrid", json={
            "enabled": True,
            "cloud_provider_type": "anthropic",
            "cloud_api_key": "sk-explicit",
            "use_env_key": "anthropic",
        })
        assert resp.status_code == 200

        # We can't read the raw key back, but we can check that the saved
        # config doesn't contain the env-source key any more by inspecting
        # the on-disk settings.json.
        from core import server as srv
        with open(srv._get_user_config_path()) as f:
            saved = json.load(f)
        api_key = saved["model"]["cloud_api"]["api_key"]
        assert api_key == "sk-explicit"

    def test_use_env_key_with_no_env_var_does_not_overwrite(self, monkeypatch, tmp_path):
        """If user clicks Detect but the env var is gone, we must not blank
        out a previously-stored key."""
        client = self._make_client(monkeypatch, tmp_path)

        # First save an explicit key.
        client.post("/api/settings/hybrid", json={
            "enabled": True,
            "cloud_provider_type": "anthropic",
            "cloud_api_key": "sk-stored",
        })

        # Now try use_env_key with no env var present.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
        client.post("/api/settings/hybrid", json={
            "enabled": True,
            "use_env_key": "anthropic",
        })

        cfg = client.get("/api/settings/hybrid").json()
        assert cfg["cloud_key_configured"] is True

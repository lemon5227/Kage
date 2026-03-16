"""Tests for ModelProvider — model abstraction layer."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from core.model_provider import (
    ModelResponse, ModelProvider,
    OpenAICompatibleProvider, create_provider_from_settings,
)


# ---------------------------------------------------------------------------
# ModelResponse
# ---------------------------------------------------------------------------

class TestModelResponse:
    def test_defaults(self):
        r = ModelResponse(text="hello")
        assert r.text == "hello"
        assert r.tool_calls == []
        assert r.emotion == "neutral"
        assert r.raw_output == ""

    def test_with_tool_calls(self):
        r = ModelResponse(
            text="ok",
            tool_calls=[{"name": "get_time", "arguments": {}}],
            emotion="happy",
        )
        assert len(r.tool_calls) == 1
        assert r.emotion == "happy"


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider
# ---------------------------------------------------------------------------

class TestOpenAICompatibleProvider:
    def test_init(self):
        provider = OpenAICompatibleProvider(
            api_key="sk-test",
            model_name="gpt-4o",
            base_url="https://api.example.com/v1",
        )
        assert provider.api_key == "sk-test"
        assert provider.model_name == "gpt-4o"

    def test_generate_parses_response(self):
        provider = OpenAICompatibleProvider(api_key="sk-test")

        fake_response = json.dumps({
            "choices": [{
                "message": {
                    "content": "Hello!",
                    "tool_calls": [],
                }
            }]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = fake_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = provider.generate(
                messages=[{"role": "user", "content": "hi"}],
            )
        assert result.text == "Hello!"

    def test_generate_parses_content_parts_array(self):
        provider = OpenAICompatibleProvider(api_key="sk-test")

        fake_response = json.dumps({
            "choices": [{
                "message": {
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": "!"},
                    ],
                    "tool_calls": [],
                }
            }]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = fake_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = provider.generate(
                messages=[{"role": "user", "content": "hi"}],
            )
        assert result.text == "Hello!"

    def test_generate_falls_back_to_reasoning_content(self):
        provider = OpenAICompatibleProvider(api_key="sk-test")

        fake_response = json.dumps({
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_content": "smoke ok",
                    "tool_calls": [],
                }
            }]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = fake_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = provider.generate(
                messages=[{"role": "user", "content": "hi"}],
            )
        assert result.text == "smoke ok"

    def test_generate_parses_tool_calls(self):
        provider = OpenAICompatibleProvider(api_key="sk-test")

        fake_response = json.dumps({
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "get_time",
                            "arguments": "{}",
                        }
                    }],
                }
            }]
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = fake_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = provider.generate(
                messages=[{"role": "user", "content": "what time"}],
            )
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "get_time"

    def test_generate_handles_network_error(self):
        provider = OpenAICompatibleProvider(api_key="sk-test")

        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = provider.generate(
                messages=[{"role": "user", "content": "hi"}],
            )
        assert "失败" in result.text
        assert result.emotion == "sad"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestCreateProviderFromSettings:
    def test_default_returns_local(self, tmp_path):
        settings = {"model": {"path": "test-model"}}
        settings_file = str(tmp_path / "settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f)

        provider = create_provider_from_settings(settings_file)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert "127.0.0.1:8080" in provider.base_url

    def test_cloud_provider_when_configured(self, tmp_path):
        settings = {
            "model": {
                "preferred_model": "cloud",
                "cloud_api": {
                    "provider": "openai",
                    "api_key": "sk-test",
                    "model_name": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                },
            }
        }
        settings_file = str(tmp_path / "settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f)

        provider = create_provider_from_settings(settings_file)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.api_key == "sk-test"

    def test_missing_settings_file(self, tmp_path):
        provider = create_provider_from_settings(
            str(tmp_path / "nonexistent.json")
        )
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_cloud_without_api_key_falls_back_to_local(self, tmp_path):
        settings = {
            "model": {
                "preferred_model": "cloud",
                "cloud_api": {"provider": "openai", "api_key": ""},
            }
        }
        settings_file = str(tmp_path / "settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f)

        provider = create_provider_from_settings(settings_file)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert "127.0.0.1:8080" in provider.base_url

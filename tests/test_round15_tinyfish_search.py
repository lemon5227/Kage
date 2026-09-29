"""Tests for Round 15 TASK-1: TinyFish search engine integration and multi-tier fallback."""

import json
from unittest.mock import MagicMock, patch
import pytest

from core.tools.web_ops import _tinyfish_api_search, tinyfish_search, tavily_search, search
from core.tool_registry import create_default_registry


def test_tinyfish_api_search_success():
    fake_response = json.dumps({
        "results": [
            {
                "title": "TinyFish Documentation",
                "url": "https://docs.tinyfish.ai",
                "snippet": "Fast free live web search for AI agents",
            },
            {
                "title": "Monid AI Tools",
                "url": "https://monid.ai",
                "content": "Discover 1800+ agent tools",
            }
        ]
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_response
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res = json.loads(_tinyfish_api_search("agent search", max_results=2, api_key="tf_test_key"))
        
        assert res.get("success") is True
        assert res.get("provider") == "tinyfish"
        assert len(res.get("results")) == 2
        assert res["results"][0]["title"] == "TinyFish Documentation"
        assert res["results"][1]["snippet"] == "Discover 1800+ agent tools"


def test_tinyfish_search_prefers_tinyfish_when_key_present(monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "tf-secret-key")
    
    with patch("core.tools.web_ops._tinyfish_api_search") as mock_tf:
        mock_tf.return_value = json.dumps({
            "success": True,
            "results": [{"title": "TinyFish Result", "url": "https://tinyfish.ai", "snippet": "Live Web"}],
            "provider": "tinyfish"
        })
        
        res = json.loads(tinyfish_search("python pytest", max_results=3))
        assert res.get("success") is True
        assert res.get("provider") == "tinyfish"
        mock_tf.assert_called_once_with("python pytest", 3, "tf-secret-key")


def test_tinyfish_search_via_monid_api(monkeypatch):
    monkeypatch.setenv("MONID_API_KEY", "monid-test-key")
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    
    with patch("core.tools.web_ops._monid_tinyfish_api_search") as mock_monid:
        mock_monid.return_value = json.dumps({
            "success": True,
            "results": [{"title": "Monid TinyFish", "url": "https://monid.ai", "snippet": "Free Search"}],
            "provider": "tinyfish"
        })
        
        res = json.loads(tinyfish_search("python pytest", max_results=3))
        assert res.get("success") is True
        assert res.get("provider") == "tinyfish"
        mock_monid.assert_called_once_with("python pytest", 3, "monid-test-key")


def test_tinyfish_search_falls_back_to_tavily(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    monkeypatch.setenv("MONID_DISABLE_AUTO_CREDENTIALS", "1")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test-key")

    with patch("core.tools.web_ops._tavily_api_search") as mock_tavily:
        mock_tavily.return_value = json.dumps({
            "success": True,
            "results": [{"title": "Tavily Result", "url": "https://tavily.com", "snippet": "Tavily search"}],
        })
        
        res = json.loads(tinyfish_search("query without tinyfish key", max_results=3))
        assert res.get("success") is True
        assert res["results"][0]["title"] == "Tavily Result"
        mock_tavily.assert_called_once()


def test_tinyfish_search_falls_back_to_duckduckgo_when_no_keys(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("MONID_DISABLE_AUTO_CREDENTIALS", "1")

    with patch("core.tools.web_ops._duckduckgo_fallback") as mock_ddg:
        mock_ddg.return_value = json.dumps({
            "success": True,
            "results": [{"title": "DDG Result", "url": "https://duckduckgo.com", "snippet": ""}],
        })
        
        res = json.loads(tinyfish_search("query no keys", max_results=2))
        assert res.get("success") is True
        assert res["results"][0]["title"] == "DDG Result"
        mock_ddg.assert_called_once()


def test_tool_registry_includes_tinyfish_search():
    reg = create_default_registry()
    assert reg.has_tool("tinyfish_search")
    assert reg.has_tool("tavily_search")


def test_search_atom_delegates_to_tinyfish(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("KAGE_TAVILY_API_KEY", raising=False)
    with patch("core.tools.web_ops.tinyfish_search") as mock_tf:
        mock_tf.return_value = json.dumps({"success": True, "results": [{"title": "TF", "url": "https://tf.ai"}]})
        res = search("test delegation", max_results=3)
        mock_tf.assert_called_once_with("test delegation", 3)
        assert "TF" in res


def test_get_monid_credentials_key_parsing(tmp_path, monkeypatch):
    from core.tools.web_ops import _get_monid_credentials_key
    fake_yaml = tmp_path / "credentials.yaml"
    fake_yaml.write_text("keys:\n  main:\n    key: monid_live_test123456\n    added_at: 2026-09-19\n", encoding="utf-8")
    
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    monkeypatch.delenv("MONID_DISABLE_AUTO_CREDENTIALS", raising=False)
    with patch("core.tools.web_ops.get_config", side_effect=lambda k, d="": str(fake_yaml) if k == "monid_credentials_path" else ""):
        key = _get_monid_credentials_key()
        assert key == "monid_live_test123456"

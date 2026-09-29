"""Tests for Round 14 ISSUE-3: Configuration loading and Tavily API key resolution.

Verifies:
1. get_config can read dotted and flat keys.
2. Environment variables override settings file.
3. core.config_loader compatibility shim works.
4. tavily_search uses api_key when configured.
"""

import json
import os
from unittest.mock import patch

from core.config import get_config
import core.config_loader as config_loader
from core.tools.web_ops import tavily_search


def test_get_config_environment_variable_override(monkeypatch):
    monkeypatch.setenv("KAGE_TAVILY_API_KEY", "env-tavily-test-key")
    assert get_config("tavily_api_key") == "env-tavily-test-key"
    assert get_config("tools.tavily_api_key") == "env-tavily-test-key"


def test_get_config_fallback_to_default():
    assert get_config("nonexistent_key_xyz", default="my_default") == "my_default"


def test_config_loader_shim(monkeypatch):
    monkeypatch.setenv("TEST_SHIM_KEY", "shim_value")
    assert config_loader.get_config("test_shim_key") == "shim_value"


def test_tavily_search_invokes_api_when_key_present(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-12345")
    
    with patch("core.tools.web_ops._tavily_api_search") as mock_api:
        mock_api.return_value = json.dumps({"success": True, "results": [{"title": "Test", "url": "https://test.com"}]})
        
        res = tavily_search("test query", max_results=3)
        mock_api.assert_called_once_with("test query", 3, "tvly-test-12345")
        assert "Test" in res


def test_tavily_search_falls_back_when_no_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("KAGE_TAVILY_API_KEY", raising=False)
    
    with patch("core.tools.web_ops.get_config", return_value=""):
        with patch("core.tools.web_ops._duckduckgo_fallback") as mock_ddg:
            mock_ddg.return_value = json.dumps({"success": True, "results": []})
            res = tavily_search("test query", max_results=3)
            mock_ddg.assert_called_once_with("test query", 3)

"""Tests for Round 14 ISSUE-7: macOS Shortcuts operations improvements."""

import json
from unittest.mock import MagicMock, patch
import pytest

from core.tools.shortcuts_ops import shortcuts_create, shortcuts_bootstrap_kage, RECOMMENDED_KAGE_SHORTCUTS


def test_shortcuts_create_empty_name_fails():
    res = json.loads(shortcuts_create(""))
    assert res.get("success") is False
    assert res.get("error") == "InvalidArgument"


def test_shortcuts_create_valid():
    with patch("subprocess.run") as mock_run:
        res = json.loads(shortcuts_create("MyCustomAction"))
        assert res.get("success") is True
        assert "MyCustomAction" in res.get("message")
        assert res.get("name") == "MyCustomAction"
        mock_run.assert_called_once()


def test_shortcuts_bootstrap_kage_identifies_installed_and_missing():
    fake_installed = f"{RECOMMENDED_KAGE_SHORTCUTS[0]}\nOther App Shortcut\n"
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_installed, returncode=0)
        res = json.loads(shortcuts_bootstrap_kage())
        
        assert res.get("success") is True
        assert res.get("message") == "Kage shortcuts bootstrapped"
        assert RECOMMENDED_KAGE_SHORTCUTS[0] in res.get("installed")
        assert len(res.get("missing")) == len(RECOMMENDED_KAGE_SHORTCUTS) - 1

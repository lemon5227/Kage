"""Contract tests for the "launch something" tools: open_url / open_app / open_website / shortcuts_create.

Only two properties are worth asserting here — the code is a dict lookup plus one
subprocess call:

  1. bad/empty input must not issue any command at all
     (this caught a real bug: ``open_app("")`` ran ``open -a ""`` and reported success);
  2. good input issues exactly one argv list, never a shell string.

The name→URL lookup table (``"b站"`` → bilibili) is deliberately not tested: it is
a dict literal whose failure is immediately visible to the user, and asserting it
does not exercise any agent behaviour. These tests used to patch
``tools_impl.open_url``, which does nothing — ``open_website`` lives in
``core.tools.web_ops`` — so pytest really opened YouTube/Bilibili and still passed
on the real return value.
"""

import json

import pytest

from core.tools import shortcuts_ops, web_ops


@pytest.fixture
def spy(monkeypatch):
    """Record every command each launch tool would run; launch nothing."""
    recorded: list[list[str]] = []
    monkeypatch.setattr(web_ops.subprocess, "run", lambda cmd, **kw: recorded.append(list(cmd)))
    monkeypatch.setattr(shortcuts_ops.subprocess, "run", lambda cmd, **kw: recorded.append(list(cmd)))
    return recorded


@pytest.mark.parametrize("call,argv", [
    (lambda: web_ops.open_url("https://kage.local/docs"), ["open", "https://kage.local/docs"]),
    (lambda: shortcuts_ops.shortcuts_create("MyShortcut"), ["open", "-a", "Shortcuts"]),
])
def test_launch_is_single_argv_list(spy, call, argv):
    """Launching must be one argv list (no shell=True string building, no extra args)."""
    out = json.loads(call())

    assert out["success"] is True
    assert spy == [argv]


def test_open_app_launches_resolved_bundle(monkeypatch):
    """open_app resolves the name to an installed .app first (D1) and launches that path as one argv list."""
    from types import SimpleNamespace
    from core.tools import app_index
    recorded: list[list[str]] = []
    monkeypatch.setattr(app_index.subprocess, "run",
                        lambda cmd, **kw: recorded.append(list(cmd)) or SimpleNamespace(returncode=0, stderr=""))
    out = json.loads(web_ops.open_app("Calculator"))

    assert out["success"] is True
    assert len(recorded) == 1 and recorded[0][0] == "open" and recorded[0][1].endswith("Calculator.app")


@pytest.mark.parametrize("call", [
    lambda: web_ops.open_url(""),
    lambda: web_ops.open_app("   "),          # whitespace-only, same guard branch
    lambda: shortcuts_ops.shortcuts_create(""),
])
def test_empty_input_never_issues_a_command(spy, call):
    """Empty input must fail cleanly instead of running `open -a ""`."""
    out = json.loads(call())

    assert out["success"] is False
    assert out["error"] == "InvalidArgument"
    assert spy == []

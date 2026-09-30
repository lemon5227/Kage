import json


def test_open_app_returns_json(monkeypatch):
    """Empty app name → canonical JSON error, and no process is launched.

    This previously executed `open -a ""` for real on every pytest run.
    """
    from core.tools import web_ops
    from core.tools_impl import open_app

    recorded: list[list[str]] = []
    monkeypatch.setattr(web_ops.subprocess, "run",
                        lambda cmd, **kw: recorded.append(list(cmd)))

    out = json.loads(open_app(""))

    assert isinstance(out, dict)
    assert out["success"] is False
    assert recorded == []


def test_smart_search_empty_query():
    from core.tools_impl import smart_search

    out = json.loads(smart_search("", 3))
    assert "error" in out

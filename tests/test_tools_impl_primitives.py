import json


def test_open_app_invalid_input():
    from core.tools_impl import open_app

    out = json.loads(open_app(""))
    assert out["success"] is False


def test_smart_search_empty_query():
    from core.tools_impl import smart_search

    out = json.loads(smart_search("", 3))
    assert out.get("error") in ("InvalidQuery", "NetworkError", "InvalidInput") or out.get("results") == []

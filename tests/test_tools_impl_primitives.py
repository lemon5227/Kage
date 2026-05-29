import json


def test_open_app_returns_json():
    from core.tools_impl import open_app

    out = json.loads(open_app(""))
    # open_app always returns valid JSON regardless of input
    assert isinstance(out, dict)


def test_smart_search_empty_query():
    from core.tools_impl import smart_search

    out = json.loads(smart_search("", 3))
    assert "error" in out

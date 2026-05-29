"""Tests for the current search() API in core.tools.web_ops."""
import json
from unittest.mock import patch


def test_search_returns_results_for_web_strategy():
    from core.tools import web_ops

    def fake_tavily(query, max_results=5):
        return json.dumps({"results": [{"title": "Example", "url": "https://example.com", "snippet": "hello"}]})

    with patch.object(web_ops, "tavily_search", side_effect=fake_tavily):
        out = json.loads(web_ops.search("kage", max_results=3))

    assert "results" in out
    assert len(out["results"]) == 1
    assert out["results"][0]["title"] == "Example"


def test_search_youtube_strategy():
    from core.tools import web_ops

    def fake_yt(query, max_results=5):
        return json.dumps({"results": [{"title": "Video", "url": "https://youtube.com/watch?v=1"}]})

    with patch.object(web_ops, "_youtube_html_search", side_effect=fake_yt):
        out = json.loads(web_ops.search("test", strategy="youtube", max_results=3))

    assert "results" in out


def test_search_bilibili_strategy():
    from core.tools import web_ops

    def fake_bili(query, sort, max_results):
        return json.dumps({"results": [{"title": "B站视频", "url": "https://bilibili.com/video/BV1"}]})

    with patch.object(web_ops, "_search_provider_bilibili", side_effect=fake_bili):
        out = json.loads(web_ops.search("test", strategy="bilibili", max_results=3))

    assert "results" in out


def test_search_empty_query_returns_error():
    from core.tools import web_ops

    out = json.loads(web_ops.search(""))
    assert "error" in out


def test_smart_search_delegates_to_search():
    from core.tools import web_ops

    def fake_tavily(query, max_results=5):
        return json.dumps({"results": [{"title": "T", "url": "U", "snippet": "S"}]})

    with patch.object(web_ops, "tavily_search", side_effect=fake_tavily):
        out = json.loads(web_ops.smart_search("kage", 2))

    assert isinstance(out.get("results"), list)


def test_search_video_intent_auto_strategy():
    from core.tools import web_ops

    def fake_yt(query, max_results=5):
        return json.dumps({"results": [{"title": "Video", "url": "https://youtube.com/watch?v=1"}]})

    def fake_bili(query, sort, max_results):
        return json.dumps({"results": []})

    with patch.object(web_ops, "_youtube_html_search", side_effect=fake_yt), \
         patch.object(web_ops, "_search_provider_bilibili", side_effect=fake_bili):
        out = json.loads(web_ops.search("看视频教程", strategy="auto", max_results=3))

    assert "results" in out
    assert out.get("strategy") == "video_auto"

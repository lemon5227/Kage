import json
from unittest.mock import patch


def test_search_returns_unified_schema_for_web_source():
    from core import tools_impl

    def fake_tavily(query, max_results=5):
        return json.dumps(
            {
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "content": "hello world",
                    }
                ]
            },
            ensure_ascii=False,
        )

    with patch.object(tools_impl, "tavily_search", side_effect=fake_tavily):
        out = json.loads(tools_impl.search("kage", source="web", max_results=3))

    assert out["success"] is True
    assert out["source_used"] == "web"
    assert isinstance(out.get("items"), list) and len(out["items"]) == 1
    item = out["items"][0]
    assert item["title"] == "Example"
    assert item["url"] == "https://example.com"
    assert item["source"] == "web"
    # Backward compatibility alias
    assert isinstance(out.get("results"), list)


def test_search_youtube_rewrites_query_and_latest_hint():
    from core import tools_impl

    captured = {"query": ""}

    def fake_tavily(query, max_results=5):
        captured["query"] = query
        return json.dumps({"results": []}, ensure_ascii=False)

    with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
        tools_impl, "tavily_search", side_effect=fake_tavily
    ):
        _ = json.loads(tools_impl.search("曹操 最新 视频", source="youtube", sort="latest", max_results=3))

    assert "site:youtube.com" in captured["query"]
    assert "最新" in captured["query"]


def test_smart_search_keeps_legacy_results_shape():
    from core import tools_impl

    def fake_tavily(query, max_results=5):
        return json.dumps({"results": [{"title": "T", "url": "U", "snippet": "S"}]}, ensure_ascii=False)

    with patch.object(tools_impl, "tavily_search", side_effect=fake_tavily):
        out = json.loads(tools_impl.smart_search("kage", 2))

    assert isinstance(out.get("results"), list)


def test_smart_search_video_intent_defaults_to_youtube():
    from core import tools_impl

    captured = {"query": ""}

    def fake_tavily(query, max_results=5):
        captured["query"] = query
        return json.dumps({"results": []}, ensure_ascii=False)

    with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
        tools_impl, "tavily_search", side_effect=fake_tavily
    ):
        _ = json.loads(tools_impl.smart_search("帮我找曹操说最新视频", 3, strategy="auto"))

    assert "site:youtube.com" in captured["query"]
    assert "最新" in captured["query"]


def test_smart_search_video_intent_respects_bilibili():
    from core import tools_impl

    captured = {"query": ""}

    def fake_tavily(query, max_results=5):
        captured["query"] = query
        return json.dumps({"results": []}, ensure_ascii=False)

    with patch.object(tools_impl, "tavily_search", side_effect=fake_tavily):
        _ = json.loads(tools_impl.smart_search("帮我找某某在b站的最新视频", 3, strategy="auto"))

    assert "site:bilibili.com" in captured["query"]


def test_search_youtube_creator_intent_preserves_raw_query_text():
    from core import tools_impl

    seen = []

    def fake_tavily(query, max_results=5):
        seen.append(query)
        return json.dumps({"results": []}, ensure_ascii=False)

    with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
        tools_impl, "tavily_search", side_effect=fake_tavily
    ):
        _ = json.loads(tools_impl.search("帮我找曹操说最新视频", source="youtube", sort="latest", max_results=3))

    assert seen
    assert "site:youtube.com" in seen[0]
    assert "曹操说" in seen[0]
    assert "帮我找曹操说最新视频" in seen[0]


def test_search_youtube_creator_intent_keeps_creator_candidate_in_results():
    from core import tools_impl

    def fake_tavily(query, max_results=5):
        return json.dumps(
            {
                "results": [
                    {
                        "title": "93分钟听完魏武帝曹操的一生",
                        "url": "https://www.youtube.com/watch?v=history1",
                        "content": "历史人物讲解",
                    },
                    {
                        "title": "曹操说 最新一期：市场观察",
                        "url": "https://www.youtube.com/watch?v=creator1",
                        "content": "频道更新",
                    },
                ]
            },
            ensure_ascii=False,
        )

    with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
        tools_impl, "tavily_search", side_effect=fake_tavily
    ):
        out = json.loads(tools_impl.search("帮我找曹操说最新视频", source="youtube", sort="latest", max_results=5))

    assert out["success"] is True
    assert any("曹操说" in str(it.get("title") or "") for it in out["items"])


def test_search_youtube_retries_with_subject_variant_when_first_empty():
    from core import tools_impl

    seen = []

    def fake_tavily(query, max_results=5):
        seen.append(query)
        if len(seen) == 1:
            return json.dumps({"results": []}, ensure_ascii=False)
        return json.dumps(
            {
                "results": [
                    {
                        "title": "曹操说 最新一期",
                        "url": "https://www.youtube.com/watch?v=ok1",
                        "content": "video",
                    }
                ]
            },
            ensure_ascii=False,
        )

    with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
        tools_impl, "tavily_search", side_effect=fake_tavily
    ):
        out = json.loads(tools_impl.search("帮我找曹操说最新视频", source="youtube", sort="latest", max_results=5))

    assert out["success"] is True
    assert len(seen) >= 2
    assert "帮我找曹操说最新视频" in seen[0]
    assert "曹操说" in seen[1]


def test_search_provider_youtube_prefers_native_youtube_results():
    from core import tools_impl

    native = json.dumps(
        {
            "results": [
                {
                    "title": "曹操说 最新一期",
                    "url": "https://www.youtube.com/watch?v=native1",
                    "snippet": "",
                }
            ]
        },
        ensure_ascii=False,
    )

    with patch.object(tools_impl, "_youtube_html_search", return_value=native), patch.object(
        tools_impl,
        "tavily_search",
        side_effect=AssertionError("tavily should not be called when native youtube has results"),
    ):
        out = json.loads(tools_impl.search("帮我找曹操说最新视频", source="youtube", sort="latest", max_results=3))

    assert out["success"] is True
    assert out["items"][0]["url"] == "https://www.youtube.com/watch?v=native1"


def test_search_youtube_video_subject_boost_prefers_channel_match():
    from core import tools_impl

    native = json.dumps(
        {
            "results": [
                {
                    "title": "曹操为什么要杀华佗？",
                    "url": "https://www.youtube.com/watch?v=history2",
                    "snippet": "历史讲解",
                },
                {
                    "title": "润不了怎么活？",
                    "url": "https://www.youtube.com/watch?v=creator2",
                    "snippet": "曹操说",
                },
            ]
        },
        ensure_ascii=False,
    )

    with patch.object(tools_impl, "_youtube_html_search", return_value=native):
        out = json.loads(tools_impl.search("帮我找曹操说最新视频", source="youtube", sort="latest", max_results=5))

    assert out["success"] is True
    assert out["items"][0]["url"] == "https://www.youtube.com/watch?v=creator2"


def test_search_youtube_filters_non_youtube_results():
    from core import tools_impl

    def fake_tavily(query, max_results=5):
        return json.dumps(
            {
                "results": [
                    {"title": "General News", "url": "https://news.example.com/a", "content": "not video"},
                    {"title": "Video A", "url": "https://www.youtube.com/watch?v=abc", "content": "video"},
                ]
            },
            ensure_ascii=False,
        )

    with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
        tools_impl, "tavily_search", side_effect=fake_tavily
    ):
        out = json.loads(tools_impl.search("曹操 视频", source="youtube", max_results=5))

    assert out["success"] is True
    assert len(out["items"]) == 1
    assert "youtube.com" in out["items"][0]["domain"]


def test_search_bilibili_filters_non_bilibili_results():
    from core import tools_impl

    def fake_tavily(query, max_results=5):
        return json.dumps(
            {
                "results": [
                    {"title": "Video B", "url": "https://www.bilibili.com/video/BV1xx", "content": "video"},
                    {"title": "Other", "url": "https://example.com/p", "content": "other"},
                ]
            },
            ensure_ascii=False,
        )

    with patch.object(tools_impl, "tavily_search", side_effect=fake_tavily):
        out = json.loads(tools_impl.search("曹操 视频", source="bilibili", max_results=5))

    assert out["success"] is True
    assert len(out["items"]) == 1
    assert "bilibili.com" in out["items"][0]["domain"]

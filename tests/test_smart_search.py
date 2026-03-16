import unittest


class TestSmartSearch(unittest.TestCase):
    def test_smart_search_preserves_user_phrase(self):
        import json
        from unittest.mock import patch
        from core import tools_impl

        captured = {"q": None}

        def fake_search(query, max_results=5):
            captured["q"] = query
            return json.dumps({"results": []}, ensure_ascii=False)

        with patch.object(tools_impl, "_youtube_html_search", return_value=json.dumps({"results": []}, ensure_ascii=False)), patch.object(
            tools_impl, "tavily_search", side_effect=fake_search
        ):
            _ = tools_impl.smart_search("曹操说 最新 血关 视频", 3, strategy="auto")

        self.assertIsNotNone(captured["q"])
        self.assertIn("血关", str(captured["q"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

import json
import unittest
from unittest.mock import patch


from core import tools_impl


class TestSearchAndOpenNormalize(unittest.TestCase):
    def test_search_and_open_preserves_user_phrase(self):
        captured = {"q": None}

        def fake_search(q, max_results=5):
            captured["q"] = q
            fake = {"results": [{"title": "YT", "url": "https://www.youtube.com/watch?v=1", "snippet": ""}]}
            return json.dumps(fake, ensure_ascii=False)

        with patch.object(tools_impl, "tavily_search", side_effect=fake_search):
            with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "url": "https://www.youtube.com/watch?v=1"}, ensure_ascii=False)):
                _ = tools_impl.search_and_open("曹操说 最新 血关 视频", prefer_domains=["youtube.com"], max_results=3)

        self.assertIsNotNone(captured["q"])
        self.assertIn("血关", str(captured["q"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

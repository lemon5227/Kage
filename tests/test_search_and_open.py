import json
import unittest
from unittest.mock import patch


from core import tools_impl


class TestSearchAndOpen(unittest.TestCase):
    def test_prefers_domain(self):
        fake = {
            "results": [
                {"title": "A", "url": "https://example.com/a", "snippet": ""},
                {"title": "YT", "url": "https://www.youtube.com/watch?v=123", "snippet": ""},
            ]
        }
        with patch.object(tools_impl, "tavily_search", return_value=json.dumps(fake, ensure_ascii=False)):
            with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "url": "https://www.youtube.com/watch?v=123"}, ensure_ascii=False)):
                out = json.loads(tools_impl.search_and_open("test", prefer_domains=["youtube.com"], max_results=5))
        self.assertTrue(out["success"])
        self.assertEqual(out["url"], "https://www.youtube.com/watch?v=123")


if __name__ == "__main__":
    unittest.main(verbosity=2)

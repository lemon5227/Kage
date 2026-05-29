import json
import unittest
from unittest.mock import patch

from core.tools import web_ops


class TestSearchAndOpen(unittest.TestCase):
    def test_prefers_domain(self):
        fake = {
            "results": [
                {"title": "A", "url": "https://example.com/a", "snippet": ""},
                {"title": "YT", "url": "https://www.youtube.com/watch?v=123", "snippet": ""},
            ]
        }
        with patch.object(web_ops, "tavily_search", return_value=json.dumps(fake)):
            with patch.object(web_ops, "open_url", return_value=json.dumps({"success": True, "opened": "https://www.youtube.com/watch?v=123"})):
                out = json.loads(web_ops.search_and_open("test", prefer_domains=["youtube.com"], max_results=5))
        self.assertTrue(out["success"])
        self.assertEqual(out["opened"], "https://www.youtube.com/watch?v=123")


if __name__ == "__main__":
    unittest.main(verbosity=2)

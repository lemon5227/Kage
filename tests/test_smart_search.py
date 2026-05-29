import json
import unittest
from unittest.mock import patch

from core.tools import web_ops


class TestSmartSearch(unittest.TestCase):
    def test_smart_search_delegates_to_search(self):
        def fake_tavily(query, max_results=5):
            return json.dumps({"results": [{"title": "T", "url": "U", "snippet": "S"}]})

        with patch.object(web_ops, "tavily_search", side_effect=fake_tavily):
            out = json.loads(web_ops.smart_search("test query", 3))

        self.assertIn("results", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

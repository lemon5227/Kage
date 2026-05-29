import json
import unittest
from unittest.mock import patch

from core.tools import web_ops


class TestSearchAndOpenNormalize(unittest.TestCase):
    def test_search_and_open_opens_first_result(self):
        def fake_search(query, max_results=5, strategy="auto", sort="relevance"):
            return json.dumps({"results": [{"title": "Result", "url": "https://example.com/1", "snippet": ""}]})

        with patch.object(web_ops, "search", side_effect=fake_search):
            with patch.object(web_ops, "open_url", return_value=json.dumps({"success": True, "opened": "https://example.com/1"})) as mock_open:
                out = json.loads(web_ops.search_and_open("test query"))

        self.assertTrue(out["success"])
        mock_open.assert_called_once_with("https://example.com/1")


if __name__ == "__main__":
    unittest.main(verbosity=2)

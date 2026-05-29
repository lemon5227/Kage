import json
import unittest
from unittest.mock import patch

from core import tools_impl


class TestOpenWebsite(unittest.TestCase):
    def test_open_website_with_known_name(self):
        with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "opened": "https://bilibili.com"})):
            out = json.loads(tools_impl.open_website("b站"))
        self.assertTrue(out["success"])

    def test_open_website_with_domain_opens_direct(self):
        with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "opened": "https://youtube.com"})):
            out = json.loads(tools_impl.open_website("youtube.com"))
        self.assertTrue(out["success"])
        self.assertEqual(out["opened"], "https://youtube.com")

    def test_open_website_with_url_opens_direct(self):
        with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "opened": "https://example.com"})):
            out = json.loads(tools_impl.open_website("https://example.com"))
        self.assertTrue(out["success"])
        self.assertEqual(out["opened"], "https://example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)

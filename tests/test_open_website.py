import json
import unittest
from unittest.mock import patch


from core import tools_impl


class TestOpenWebsite(unittest.TestCase):
    def test_open_website_with_name_uses_search(self):
        fake = {"results": [{"title": "YouTube", "url": "https://www.youtube.com", "snippet": ""}]}
        with patch.object(tools_impl, "tavily_search", return_value=json.dumps(fake, ensure_ascii=False)):
            with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "url": "https://www.youtube.com"}, ensure_ascii=False)):
                out = json.loads(tools_impl.open_website("油管"))
        self.assertTrue(out["success"])

    def test_open_website_with_domain_opens_direct(self):
        with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "url": "https://youtube.com"}, ensure_ascii=False)):
            out = json.loads(tools_impl.open_website("youtube.com"))
        self.assertTrue(out["success"])
        self.assertEqual(out["url"], "https://youtube.com")

    def test_open_website_with_url_opens_direct(self):
        with patch.object(tools_impl, "open_url", return_value=json.dumps({"success": True, "url": "https://example.com"}, ensure_ascii=False)):
            out = json.loads(tools_impl.open_website("https://example.com"))
        self.assertTrue(out["success"])
        self.assertEqual(out["url"], "https://example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest


from core.server import KageServer
from core.session_state import SessionState


class DummyTools:
    def system_control(self, target, action, value=None):
        return f"{target}:{action}" + (f":{value}" if value else "")

    def open_url(self, url):
        return f"open_url:{url}"

    def open_app(self, app_name):
        return f"open_app:{app_name}"

    def get_time(self):
        return "00:00"

    def take_screenshot(self):
        return "ok"

    def web_search(self, query: str, max_results: int = 5):
        return f"search:{query}:{max_results}"


class TestFastCommandRouting(unittest.TestCase):
    def setUp(self):
        self.s = object.__new__(KageServer)
        self.s.tools = DummyTools()
        self.s.session = SessionState()
        self.s._fast_cache = {}

        # Make weather deterministic and offline.
        self.s._get_effective_city = lambda: "Nice"
        self.s._fetch_weather = lambda city: f"{city}: sunny"

    def test_network_query_weather_does_not_toggle_wifi(self):
        out = self.s._fast_command("网络查询尼斯天气怎么样？")
        self.assertIn("search:", str(out))
        self.assertNotIn("wifi:", str(out).lower())

    def test_open_site_is_not_fast_path(self):
        self.assertIsNone(self.s._fast_command("帮我打开youtube网站。"))
        self.assertIsNone(self.s._fast_command("帮我打开油管"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

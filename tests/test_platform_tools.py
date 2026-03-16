from core.tool_registry import ToolRegistry


class _DummyTools:
    def open_app(self, app_name):
        return f"opened:{app_name}"

    def open_website(self, site):
        return f"site:{site}"

    def smart_search(self, query, max_results=5, strategy="auto"):
        return f"search:{query}:{max_results}:{strategy}"

    def search_and_open(self, query, prefer_domains=None, max_results=5):
        return f"open:{query}:{prefer_domains}:{max_results}"

    def system_control(self, target, action, value=None):
        return f"sys:{target}:{action}:{value}"

    def get_time(self):
        return "now"


def test_register_platform_tools_registers_expected_tools():
    from core.platform_tools import register_platform_tools

    reg = ToolRegistry()
    register_platform_tools(reg, _DummyTools())

    for name in [
        "open_app",
        "open_website",
        "smart_search",
        "search_and_open",
        "system_control",
        "get_time",
    ]:
        assert reg.has_tool(name)

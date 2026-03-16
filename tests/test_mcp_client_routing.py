import unittest


try:
    from skills import mcp_client  # type: ignore
except Exception:
    mcp_client = None


class TestMcpClientRouting(unittest.TestCase):
    def setUp(self):
        if mcp_client is None:
            raise unittest.SkipTest("skills.mcp_client not available in this refactor")

    def test_select_server_command_prefers_explicit_server(self):
        cfg = {
            "servers": {
                "a": {"command": ["echo", "a"]},
                "b": {"command": ["echo", "b"]},
            },
            "default_server": "a",
        }
        cmd = mcp_client._select_server_command(cfg, tool_name="search", server="b")
        self.assertEqual(cmd, ["echo", "b"])

    def test_select_server_command_uses_tool_map(self):
        cfg = {
            "servers": {
                "fs": {"command": ["echo", "fs"]},
                "ddg": {"command": ["echo", "ddg"]},
            },
            "default_server": "fs",
            "tool_map": {"search": "ddg"},
        }
        cmd = mcp_client._select_server_command(cfg, tool_name="search", server=None)
        self.assertEqual(cmd, ["echo", "ddg"])

    def test_parse_command_substitutes_kage_root(self):
        root = mcp_client._get_app_root()
        cmd = mcp_client._parse_command(["echo", "{KAGE_ROOT}"])
        self.assertEqual(cmd[1], root)


if __name__ == "__main__":
    unittest.main(verbosity=2)

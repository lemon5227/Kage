import unittest


from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry, ToolDefinition


class TestToolCallParsingMulti(unittest.TestCase):
    def setUp(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="smart_search",
            description="x",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query, max_results=5, strategy="auto": "ok",
            safety_level="SAFE",
        ))
        reg.register(ToolDefinition(
            name="open_website",
            description="x",
            parameters={"type": "object", "properties": {"site": {"type": "string"}}},
            handler=lambda site: "ok",
            safety_level="SAFE",
        ))
        self.t = ToolExecutor(tool_registry=reg, workspace_dir="~/.kage")

    def test_parse_multiple_bracket_tool_calls(self):
        text = (
            "<|tool_call_start|>[smart_search(query=\"kage\")]<|tool_call_end|>"
            " some text "
            "<|tool_call_start|>[open_website(site=\"youtube\")]<|tool_call_end|>"
        )
        calls = self.t.parse_tool_calls(text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["name"], "smart_search")
        self.assertEqual(calls[1]["name"], "open_website")


if __name__ == "__main__":
    unittest.main(verbosity=2)

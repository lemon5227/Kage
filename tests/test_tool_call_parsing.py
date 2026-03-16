import unittest


from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry, ToolDefinition


class TestToolCallParsing(unittest.TestCase):
    def setUp(self):
        reg = ToolRegistry()
        # Minimal registry for parsing test
        reg.register(ToolDefinition(
            name="find_skills",
            description="x",
            parameters={"type": "object", "properties": {}},
            handler=lambda query="", max_results=5, skills_dir="skills": "ok",
            safety_level="SAFE",
        ))
        self.t = ToolExecutor(tool_registry=reg, workspace_dir="~/.kage")

    def test_parse_hyphenated_tool_name_bracket(self):
        text = "<|tool_call_start|>[find-skills(script=\"list.sh\")]<|tool_call_end|>"
        calls = self.t.parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        # Hyphenated name is normalized to underscore.
        self.assertEqual(calls[0]["name"], "find_skills")


if __name__ == "__main__":
    unittest.main(verbosity=2)

import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from core.tools import KageTools


def run():
    tools = KageTools()
    print("Loaded skills:", ", ".join(sorted(tools.skills.keys())))

    trigger_result = tools.execute_trigger("帮我记一下：今天开会")
    print("Trigger result:", trigger_result)

    tool_call_text = "<|tool_call|>[{\"name\": \"calc\", \"arguments\": {\"expression\": \"2+2\"}}]<|/tool_call|>"
    tool_calls = tools.parse_tool_calls(tool_call_text)
    print("Parsed tool_calls:", tool_calls)
    for call in tool_calls:
        result = tools.execute_tool_call(call.get("name"), call.get("arguments"))
        print("Tool result:", result)

    json_tool_calls = json.dumps([
        {"name": "quick_note", "arguments": {"text": "测试笔记"}},
        {"name": "calc", "arguments": {"expression": "10/2"}},
    ])
    tool_calls = tools.parse_tool_calls(json_tool_calls)
    print("Parsed json tool_calls:", tool_calls)
    for call in tool_calls:
        result = tools.execute_tool_call(call.get("name"), call.get("arguments"))
        print("Tool result:", result)


if __name__ == "__main__":
    run()

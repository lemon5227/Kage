import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from core.brain import KageBrain
from core.tools import KageTools


def collect_stream(stream):
    text = ""
    for chunk in stream:
        piece = getattr(chunk, "text", str(chunk))
        text += piece
    return text.strip()


def run_case(brain: KageBrain, tools: KageTools, user_input: str):
    print("\n=== User ===")
    print(user_input)

    trigger_result = tools.execute_trigger(user_input)
    if trigger_result is not None:
        print("=== Tool Result ===")
        print(trigger_result)
        print("=== Kage ===")
        print(str(trigger_result))
        return

    response = collect_stream(brain.think(user_input, memories=[], current_emotion="neutral", mode="action"))
    tool_calls = tools.parse_tool_calls(response)
    if tool_calls:
        results = []
        for call in tool_calls:
            name = call.get("name")
            arguments = call.get("arguments") or call.get("parameters")
            result = tools.execute_tool_call(name, arguments)
            results.append(f"{name}: {result}")
        tool_result = "\n".join(results)
        print("=== Tool Result ===")
        print(tool_result)
        print("=== Kage ===")
        print(tool_result)
        return

    if ">>>ACTION:" in response:
        parts = response.split(">>>ACTION:")
        raw_cmd = parts[1].strip()
        tool_result = tools.execute(raw_cmd)
        print("=== Tool Result ===")
        print(tool_result)
        print("=== Kage ===")
        print(str(tool_result))
        return

    print("=== Kage ===")
    print(response)


def run():
    brain = KageBrain()
    tools = KageTools()

    cases = [
        "帮我记一下：今天开会",
        "计算 12*(3+4)",
        "列目录 /Users/wenbo/Kage",
        "读文件 /Users/wenbo/Kage/readme.md",
        "搜索代码 KageTools",
        "帮我写社媒内容",
        "帮我找技能",
        "做一个PPT",
        "写文档",
        "做个表格",
        "处理PDF",
        "用playwright测试网页 https://example.com",
    ]

    for user_input in cases:
        run_case(brain, tools, user_input)


if __name__ == "__main__":
    run()

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from core.tools import KageTools


def run():
    tools = KageTools()
    test_path = os.path.join(ROOT_DIR, "temp_mcp_test.txt")

    print("MCP list:")
    print(tools.execute_tool_call("mcp_fs_list", {"path": ROOT_DIR}))

    print("\nMCP write:")
    print(tools.execute_tool_call("mcp_fs_write", {"path": test_path, "content": "mcp test"}))

    print("\nMCP read:")
    print(tools.execute_tool_call("mcp_fs_read", {"path": test_path}))


if __name__ == "__main__":
    run()

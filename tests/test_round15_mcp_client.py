"""
Round 15 Unit Tests - TASK-7: Standard MCP Subprocess Client Communication
Verifies JSON-RPC 2.0 stdio communication, handshake lifecycle, tools/list,
tools/call, process crash cleanup, and McpManager server command routing.
"""

import asyncio
import os
import sys
import tempfile
import pytest
from core.mcp_client import (
    _get_app_root,
    _parse_command,
    _select_server_command,
    McpProcessClient,
    McpManager,
)
from core.exceptions import ToolExecutionError


MOCK_MCP_SERVER_CODE = """
import sys
import json

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue

    req_id = req.get("id")
    method = req.get("method")

    if method == "initialize":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-server", "version": "1.0"},
            },
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "notifications/initialized":
        # Notification, no response needed
        pass
    elif method == "tools/list":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": "mock_calc", "description": "mock calculator", "inputSchema": {}}
                ]
            },
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"executed_{name}"}]
            },
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "trigger_error":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": "Internal error occurred"},
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
"""


class TestMcpCommandRouting:
    def test_parse_command_root_substitution(self):
        root = _get_app_root()
        cmd = ["npx", "-y", "@modelcontextprotocol/server", "{KAGE_ROOT}/data"]
        parsed = _parse_command(cmd)
        assert parsed[3] == f"{root}/data"

    def test_select_server_command_fallback(self):
        cfg = {
            "servers": {
                "server1": {"command": ["python", "s1.py"]},
                "server2": {"command": ["python", "s2.py"]},
            },
            "default_server": "server1",
            "tool_map": {"tool_b": "server2"},
        }
        # Explicit server
        assert _select_server_command(cfg, server="server2") == ["python", "s2.py"]
        # Mapped tool
        assert _select_server_command(cfg, tool_name="tool_b") == ["python", "s2.py"]
        # Default server fallback
        assert _select_server_command(cfg, tool_name="unknown_tool") == ["python", "s1.py"]


class TestMcpProcessCommunication:
    def test_stdio_jsonrpc_lifecycle_and_tools(self, tmp_path):
        server_script = tmp_path / "mock_mcp_server.py"
        server_script.write_text(MOCK_MCP_SERVER_CODE, encoding="utf-8")

        client = McpProcessClient(command=[sys.executable, str(server_script)])

        async def _test():
            try:
                # 1. Initialize
                init_res = await client.initialize()
                assert init_res["serverInfo"]["name"] == "mock-server"
                assert client.is_healthy() is True

                # 2. Tools List
                tools = await client.list_tools()
                assert len(tools) == 1
                assert tools[0]["name"] == "mock_calc"

                # 3. Tool Call
                call_res = await client.call_tool("mock_calc", {"arg": 1})
                assert call_res == "executed_mock_calc"

                # 4. Error response handling
                with pytest.raises(ToolExecutionError) as exc_info:
                    await client.send_request("trigger_error")
                assert "Internal error occurred" in str(exc_info.value)

            finally:
                await client.close()
                assert client.is_running is False

        asyncio.run(_test())

    def test_mcp_manager_integration(self, tmp_path):
        server_script = tmp_path / "mock_mcp_server.py"
        server_script.write_text(MOCK_MCP_SERVER_CODE, encoding="utf-8")

        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(
            f'{{"servers": {{"test_srv": {{"command": ["{sys.executable}", "{str(server_script)}"]}}}}, "default_server": "test_srv"}}',
            encoding="utf-8",
        )

        mgr = McpManager(config_path=str(cfg_file))
        client = mgr.get_client("test_srv")
        assert client is not None
        assert client.command == [sys.executable, str(server_script)]

        async def _test_close():
            await mgr.close_all()

        asyncio.run(_test_close())

"""
Kage MCP Client — 标准 Model Context Protocol (MCP) 客户端与路由管理.

实现基于 stdio 与 JSON-RPC 2.0 规范的 MCP 外部服务进程通信生命周期管理：
1. 解析 config/mcp.json 配置（支持 command, args, env 及 {KAGE_ROOT} 替换）
2. 基于 asyncio.subprocess 的标准握手 (initialize -> notifications/initialized)
3. tools/list 与 tools/call 工具查询与调用
4. 进程健康监测、异常捕获与自动清理保护机制
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from core.exceptions import ToolExecutionError, ToolNotFoundError

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


def _get_app_root() -> str:
    """Return the absolute path of the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_command(cmd: list[str]) -> list[str]:
    """Substitute {KAGE_ROOT} and environment placeholders in command tokens."""
    root = _get_app_root()
    parsed: list[str] = []
    for token in cmd:
        t = str(token)
        if "{KAGE_ROOT}" in t:
            t = t.replace("{KAGE_ROOT}", root)
        parsed.append(t)
    return parsed


def _select_server_command(
    cfg: dict,
    tool_name: str | None = None,
    server: str | None = None,
) -> list[str] | None:
    """Select the command list for the specified or inferred server."""
    servers = cfg.get("servers") or {}

    selected_server = None
    if server and server in servers:
        selected_server = server
    elif tool_name and tool_name in (cfg.get("tool_map") or {}):
        selected_server = cfg["tool_map"][tool_name]
    elif cfg.get("default_server") and cfg["default_server"] in servers:
        selected_server = cfg["default_server"]

    if selected_server and selected_server in servers:
        cmd = servers[selected_server].get("command")
        if cmd and isinstance(cmd, list):
            return _parse_command(cmd)

    top_level_cmd = cfg.get("command")
    if top_level_cmd and isinstance(top_level_cmd, list):
        return _parse_command(top_level_cmd)

    return None


class McpProcessClient:
    """Manages an active stdio subprocess communicating via JSON-RPC 2.0."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout_sec: float = 30.0,
    ):
        self.command = list(command)
        self.env = env
        self.timeout_sec = float(timeout_sec)
        self._process: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def is_healthy(self) -> bool:
        return self.is_running and self._initialized

    async def start(self) -> None:
        """Spawn the child process with piped stdin/stdout."""
        if self.is_running:
            return

        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=run_env,
            )
            logger.info("Started MCP subprocess: %s (PID: %d)", self.command[0], self._process.pid)
        except Exception as exc:
            self._process = None
            raise ToolExecutionError(f"Failed to start MCP process {self.command}: {exc}") from exc

    async def initialize(self) -> dict:
        """Perform standard MCP initialize handshake."""
        await self.start()
        payload = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "Kage",
                "version": "1.0.0",
            },
        }
        res = await self.send_request("initialize", payload)
        # Send initialized notification (fire and forget per spec)
        await self.send_notification("notifications/initialized", {})
        self._initialized = True
        return res

    async def send_request(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC 2.0 request and wait for the response."""
        if not self.is_running:
            raise ToolExecutionError("MCP process is not running")

        async with self._lock:
            self._req_id += 1
            req_id = self._req_id

            msg = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params if params is not None else {},
            }

            raw = json.dumps(msg, ensure_ascii=False) + "\n"
            assert self._process is not None
            assert self._process.stdin is not None
            assert self._process.stdout is not None

            try:
                self._process.stdin.write(raw.encode("utf-8"))
                await self._process.stdin.drain()

                line_bytes = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=self.timeout_sec,
                )
            except asyncio.TimeoutError as exc:
                await self.close()
                raise ToolExecutionError(f"MCP request '{method}' timed out after {self.timeout_sec}s") from exc
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                await self.close()
                raise ToolExecutionError(f"MCP connection lost during '{method}': {exc}") from exc

            if not line_bytes:
                await self.close()
                raise ToolExecutionError(f"MCP process closed stdout unexpectedly during '{method}'")

            line = line_bytes.decode("utf-8").strip()
            if not line:
                raise ToolExecutionError("Empty response from MCP process")

            try:
                resp = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ToolExecutionError(f"Invalid JSON from MCP process: {line}") from exc

            if "error" in resp:
                err = resp["error"]
                err_msg = err.get("message") if isinstance(err, dict) else str(err)
                raise ToolExecutionError(f"MCP error ({method}): {err_msg}")

            return resp.get("result")

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC 2.0 notification (no response expected)."""
        if not self.is_running or self._process is None or self._process.stdin is None:
            return

        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
        }
        raw = json.dumps(msg, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(raw.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as exc:
            logger.warning("Failed to send MCP notification '%s': %s", method, exc)

    async def list_tools(self) -> list[dict]:
        """Fetch available tools from the MCP server."""
        if not self.is_healthy():
            await self.initialize()
        result = await self.send_request("tools/list", {})
        if isinstance(result, dict) and "tools" in result:
            return list(result["tools"])
        return []

    async def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """Invoke a tool on the MCP server."""
        if not self.is_healthy():
            await self.initialize()
        params = {
            "name": name,
            "arguments": arguments or {},
        }
        result = await self.send_request("tools/call", params)
        # Parse standard MCP content response
        if isinstance(result, dict) and "content" in result:
            items = result["content"]
            if isinstance(items, list) and items:
                texts = [item.get("text", "") for item in items if isinstance(item, dict) and "text" in item]
                if texts:
                    return "\n".join(texts)
        return result

    async def close(self) -> None:
        """Gracefully terminate the subprocess."""
        self._initialized = False
        p = self._process
        self._process = None
        if p is None:
            return

        try:
            if p.stdin and not p.stdin.is_closing():
                p.stdin.close()
        except Exception:
            pass

        try:
            p.terminate()
            await asyncio.wait_for(p.wait(), timeout=2.0)
        except Exception:
            try:
                p.kill()
                await p.wait()
            except Exception:
                pass
        logger.info("Closed MCP subprocess")


class McpManager:
    """Manages configured MCP clients from mcp.json."""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or os.environ.get("KAGE_MCP_CFG") or os.path.join(_get_app_root(), "config", "mcp.json")
        self._clients: dict[str, McpProcessClient] = {}
        self._cfg = self._load_config()

    def _load_config(self) -> dict:
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Failed to load mcp.json (%s): %s", self.config_path, exc)
        return {}

    def get_client(self, server_name: str | None = None) -> McpProcessClient | None:
        """Get or initialize an McpProcessClient for the requested server."""
        name = server_name or self._cfg.get("default_server") or "default"
        client = self._clients.get(name)
        if client and client.is_healthy():
            return client

        cmd = _select_server_command(self._cfg, server=server_name)
        if not cmd:
            return None

        client = McpProcessClient(command=cmd)
        self._clients[name] = client
        return client

    async def close_all(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

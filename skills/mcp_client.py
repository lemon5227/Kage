"""
Legacy compatibility wrapper for MCP client routing.
Delegates to core.mcp_client.
"""

from core.mcp_client import (
    _get_app_root,
    _parse_command,
    _select_server_command,
    McpProcessClient,
    McpManager,
)

__all__ = [
    "_get_app_root",
    "_parse_command",
    "_select_server_command",
    "McpProcessClient",
    "McpManager",
]

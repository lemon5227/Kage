"""core.platform_tools

Wrappers that expose platform-facing assistant capabilities as ToolRegistry tools.

These handlers delegate to an injected `tools` object (legacy compatibility),
so we can keep the agent loop and tool execution unified while iterating on
implementations.
"""

from __future__ import annotations

from core.tool_registry import ToolRegistry, ToolDefinition


def register_platform_tools(registry: ToolRegistry, tools) -> None:
    """Register platform tools backed by a `tools` implementation."""
    # --- App / URL ---
    if not registry.has_tool("open_app"):
        registry.register(ToolDefinition(
            name="open_app",
            description="打开一个本机应用。当用户说打开/启动某个应用时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "应用名称，例如 Safari/微信/Visual Studio Code"},
                },
                "required": ["app_name"],
            },
            handler=lambda app_name: tools.open_app(app_name),
            safety_level="SAFE",
        ))

    if not registry.has_tool("open_website"):
        registry.register(ToolDefinition(
            name="open_website",
            description="打开一个网站（可给网站名或域名）。会自动搜索官网并打开。",
            parameters={
                "type": "object",
                "properties": {
                    "site": {"type": "string", "description": "网站名、域名或 URL"},
                },
                "required": ["site"],
            },
            handler=lambda site: tools.open_website(site),
            safety_level="SAFE",
        ))

    # --- Search helpers ---
    if hasattr(tools, "search") and not registry.has_tool("search"):
        registry.register(ToolDefinition(
            name="search",
            description="统一检索原子操作。支持 source=auto/web/youtube/bilibili，返回标准化结果列表。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "source": {"type": "string", "description": "auto|web|youtube|bilibili", "default": "auto"},
                    "sort": {"type": "string", "description": "relevance|latest", "default": "relevance"},
                    "max_results": {"type": "integer", "description": "最大结果数 (1-10)", "default": 5},
                    "filters": {"type": "object", "description": "可选过滤条件", "default": {}},
                },
                "required": ["query"],
            },
            handler=lambda query, source="auto", sort="relevance", max_results=5, filters=None: tools.search(
                query,
                source=source,
                sort=sort,
                max_results=max_results,
                filters=filters,
            ),
            safety_level="SAFE",
        ))

    if not registry.has_tool("smart_search"):
        registry.register(ToolDefinition(
            name="smart_search",
            description="智能网页搜索（可自动选择策略）。用于查资料、查新闻来源、核验信息等。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "最大结果数 (1-8)", "default": 5},
                    "strategy": {"type": "string", "description": "auto|ddg|mcp", "default": "auto"},
                },
                "required": ["query"],
            },
            handler=lambda query, max_results=5, strategy="auto": tools.smart_search(query, max_results=max_results, strategy=strategy),
            safety_level="SAFE",
        ))

    if not registry.has_tool("search_and_open"):
        registry.register(ToolDefinition(
            name="search_and_open",
            description="搜索并直接打开最佳结果。适合“帮我找…然后打开”。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "prefer_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "优先域名列表，例如 [bilibili.com]",
                        "default": [],
                    },
                    "max_results": {"type": "integer", "description": "最大结果数 (1-8)", "default": 5},
                },
                "required": ["query"],
            },
            handler=lambda query, prefer_domains=None, max_results=5: tools.search_and_open(query, prefer_domains=prefer_domains, max_results=max_results),
            safety_level="SAFE",
        ))

    # --- System control ---
    # Prefer the structured implementation registered in the default registry.
    # Only register legacy system_control if none exists.
    if not registry.has_tool("system_control"):
        registry.register(ToolDefinition(
            name="system_control",
            description=(
                "统一系统控制入口。用于调节音量/亮度，或开关 WiFi/蓝牙，或打开/关闭应用。"
                "注意：可能改变系统状态。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "volume|brightness|wifi|bluetooth|app"},
                    "action": {"type": "string", "description": "up|down|on|off|open|close|mute|unmute"},
                    "value": {"type": "string", "description": "可选：应用名或具体值", "default": ""},
                },
                "required": ["target", "action"],
            },
            handler=lambda target, action, value="": tools.system_control(target, action, value or None),
            safety_level="SAFE",
        ))

    # --- Misc ---
    if not registry.has_tool("get_time"):
        registry.register(ToolDefinition(
            name="get_time",
            description="获取当前时间。",
            parameters={"type": "object", "properties": {}},
            handler=lambda: tools.get_time(),
            safety_level="SAFE",
        ))

    if hasattr(tools, "take_screenshot") and not registry.has_tool("take_screenshot"):
        registry.register(ToolDefinition(
            name="take_screenshot",
            description="截图并保存到桌面。",
            parameters={"type": "object", "properties": {}},
            handler=lambda: tools.take_screenshot(),
            safety_level="SAFE",
        ))

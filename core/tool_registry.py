"""
Tool Registry - 工具注册表核心模块

集中管理所有工具的 JSON Schema 定义、加载和注册。
"""

from dataclasses import dataclass
from typing import Callable, Optional
import logging
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """单个工具的完整定义"""
    name: str
    description: str  # 包含使用场景的详细描述
    parameters: dict  # JSON Schema 格式的参数定义
    handler: Callable  # 工具执行函数
    safety_level: str = "SAFE"  # "SAFE" 或 "DANGEROUS"


class ToolRegistry:
    """工具注册表：集中管理所有工具定义"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        """注册工具。名称冲突时覆盖并记录警告。"""
        # 验证必需字段
        if not tool_def.name:
            raise ValueError("工具定义缺少必需字段: name")
        if not tool_def.description:
            raise ValueError(f"工具定义缺少必需字段: description (tool: {tool_def.name})")
        if not tool_def.parameters:
            raise ValueError(f"工具定义缺少必需字段: parameters (tool: {tool_def.name})")
        if not tool_def.handler:
            raise ValueError(f"工具定义缺少必需字段: handler (tool: {tool_def.name})")
        
        # 名称冲突时覆盖并记录警告
        if tool_def.name in self._tools:
            logger.warning("覆盖已存在的工具: %s", tool_def.name)
        
        self._tools[tool_def.name] = tool_def

    def get_handler(self, tool_name: str) -> Optional[Callable]:
        """获取工具的 handler 函数，不存在返回 None。"""
        tool = self._tools.get(tool_name)
        return tool.handler if tool else None

    def get_security_level(self, tool_name: str) -> str:
        """获取工具的安全等级，不存在返回 'SAFE'。"""
        tool = self._tools.get(tool_name)
        return tool.safety_level if tool else "SAFE"

    def get_all_schemas(self) -> list[dict]:
        """返回所有工具的 OpenAI Function Calling 格式 Schema。"""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            })
        return schemas

    def get_tool_descriptions(self) -> str:
        """返回所有工具的文本描述（用于系统提示词）。"""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    def get_tool_names(self) -> list[str]:
        """返回所有已注册工具名称。"""
        return list(self._tools.keys())

    def has_tool(self, tool_name: str) -> bool:
        """检查工具是否已注册。"""
        return tool_name in self._tools


def _register_mcp_dynamic_aliases(registry: ToolRegistry, mcp_cfg_path: str | None = None) -> None:
    """Register lightweight aliases from MCP config tool_map.

    This does not execute MCP directly; it exposes config-declared tool names
    as aliases to existing safe primitives, so newly declared tools are
    discoverable by the model without core code edits.
    """
    path = str(mcp_cfg_path or os.environ.get("KAGE_MCP_CFG") or "/Users/wenbo/Kage/config/mcp.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return
    if not isinstance(cfg, dict):
        return
    tool_map = cfg.get("tool_map")
    if not isinstance(tool_map, dict):
        return

    try:
        from core.tools_impl import smart_search, web_fetch
    except Exception:
        return

    for alias, _server in tool_map.items():
        name = str(alias or "").strip()
        if not name or registry.has_tool(name):
            continue

        low = name.lower()
        if low in ("search", "web_search", "lookup"):
            registry.register(ToolDefinition(
                name=name,
                description=f"MCP alias `{name}`: map to smart_search for web lookup.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
                handler=lambda query, max_results=5: smart_search(query=query, max_results=max_results, strategy="auto"),
                safety_level="SAFE",
            ))
            continue

        if low in ("fetch_content", "fetch", "read_url"):
            registry.register(ToolDefinition(
                name=name,
                description=f"MCP alias `{name}`: fetch webpage content by URL.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "网页 URL"},
                    },
                    "required": ["url"],
                },
                handler=lambda url: web_fetch(url=url),
                safety_level="SAFE",
            ))
            continue



def create_default_registry(memory_system=None) -> ToolRegistry:
    """创建并注册所有 7 个核心工具的 Registry。"""
    from core.tools_impl import (
        tavily_search, web_fetch, exec_command,
        find_skills, memory_search, proactive_agent, open_url,
        skills_find_remote, skills_install, skills_list, skills_read,
        fs_move, fs_rename, fs_write, fs_trash, fs_undo_last,
        fs_search, fs_preview, fs_apply,
        system_control as system_control_tool, system_capabilities as system_capabilities_tool,
        shortcuts_list, shortcuts_run, shortcuts_view,
        get_time, open_app, open_website, smart_search, search_and_open, take_screenshot,
        search,
        skills_save_local,
    )
    import functools

    registry = ToolRegistry()

    registry.register(ToolDefinition(
        name="tavily_search",
        description="搜索网页信息。当用户想查找资料、新闻、技术文档、视频等网络内容时使用。支持中英文搜索。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最大结果数 (1-10)", "default": 5},
            },
            "required": ["query"],
        },
        handler=tavily_search,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="web_fetch",
        description="获取并阅读网页内容。当需要理解搜索结果的详细内容、阅读文章、查看网页信息时使用。返回网页的纯文本内容。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要获取的网页 URL"},
            },
            "required": ["url"],
        },
        handler=web_fetch,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="exec",
        description="执行 shell 命令。当需要运行系统命令、打开应用(open -a App)、安装软件(brew install)、控制系统(音量/亮度)、查看系统信息时使用。",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数 (1-120)", "default": 30},
            },
            "required": ["command"],
        },
        handler=exec_command,
        # Policy: only deletion-like actions should require confirmation.
        # `exec` itself is classified SAFE; ToolExecutor performs extra checks
        # for deletion patterns (e.g. rm) and will request confirmation.
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="find_skills",
        description="搜索可用的技能文件。当遇到不确定如何完成的任务时，搜索 skills/ 目录下的 SKILL.md 技能指令文件寻找解决方案。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的任务描述"},
                "max_results": {"type": "integer", "description": "最大结果数 (1-5)", "default": 5},
            },
            "required": ["query"],
        },
        handler=find_skills,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="skills_find_remote",
        description=(
            "在 skills.sh 生态中搜索可用技能（通过 npx skills find）。"
            "当你不确定有没有现成流程模板/技能可以复用时使用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的需求关键词"},
                "max_results": {"type": "integer", "description": "最大结果数 (1-10)", "default": 5},
            },
            "required": ["query"],
        },
        handler=skills_find_remote,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="skills_install",
        description=(
            "安装 skills.sh 生态中的技能（通过 npx skills add）。"
            "用于把远程技能安装到本机以便后续复用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "GitHub owner/repo 或 Git URL"},
                "skill": {"type": "string", "description": "技能名称（frontmatter name）"},
                "global_install": {"type": "boolean", "description": "是否全局安装", "default": True},
                "agent": {"type": "string", "description": "目标 agent 名称", "default": "opencode"},
            },
            "required": ["repo", "skill"],
        },
        handler=skills_install,
        # Project policy: skills.sh-discovered installs are non-interactive.
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="skills_list",
        description="列出已安装的技能（通过 npx skills list）。",
        parameters={
            "type": "object",
            "properties": {
                "global_install": {"type": "boolean", "description": "是否列出全局安装", "default": True},
                "agent": {"type": "string", "description": "目标 agent 名称", "default": "opencode"},
            },
        },
        handler=skills_list,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="skills_read",
        description="读取某个已安装技能的 SKILL.md 内容（按技能 name 查找）。",
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "技能 name（frontmatter name）"},
            },
            "required": ["skill_name"],
        },
        handler=skills_read,
        safety_level="SAFE",
    ))

    # memory_search 需要绑定 memory_system 实例
    ms_handler = functools.partial(memory_search, memory_system=memory_system)
    registry.register(ToolDefinition(
        name="memory_search",
        description="搜索对话记忆。当需要回忆之前的对话内容、用户偏好、历史操作记录时使用。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "n_results": {"type": "integer", "description": "最大结果数", "default": 5},
            },
            "required": ["query"],
        },
        handler=ms_handler,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="proactive_agent",
        description="创建新的技能文件。当发现一个有用的操作流程值得保存为可复用技能时使用。会在 skills/ 目录下创建 SKILL.md 文件。",
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "技能名称（英文，用作文件名）"},
                "description": {"type": "string", "description": "技能描述"},
                "steps": {"type": "string", "description": "执行步骤说明"},
            },
            "required": ["skill_name", "description"],
        },
        handler=proactive_agent,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="open_url",
        description="在默认浏览器中打开网页。当用户明确要求打开某个 URL 或网站时使用。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要打开的 URL"},
            },
            "required": ["url"],
        },
        handler=open_url,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="get_time",
        description="获取当前时间。",
        parameters={"type": "object", "properties": {}},
        handler=get_time,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="open_app",
        description="打开一个本机应用。",
        parameters={
            "type": "object",
            "properties": {"app_name": {"type": "string", "description": "应用名"}},
            "required": ["app_name"],
        },
        handler=open_app,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="open_website",
        description="打开网站（可输入网站名/域名/URL）。",
        parameters={
            "type": "object",
            "properties": {"site": {"type": "string", "description": "网站名/域名/URL"}},
            "required": ["site"],
        },
        handler=open_website,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="search",
        description="统一检索原子操作。支持 source=auto/web/youtube/bilibili，返回标准化结果列表。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "source": {"type": "string", "description": "auto|web|youtube|bilibili", "default": "auto"},
                "sort": {"type": "string", "description": "relevance|latest", "default": "relevance"},
                "max_results": {"type": "integer", "default": 5},
                "filters": {"type": "object", "default": {}},
            },
            "required": ["query"],
        },
        handler=search,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="smart_search",
        description="智能网页搜索（返回结构化结果列表）。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "default": 5},
                "strategy": {"type": "string", "default": "auto"},
            },
            "required": ["query"],
        },
        handler=smart_search,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="search_and_open",
        description="搜索并打开最佳结果。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "prefer_domains": {"type": "array", "items": {"type": "string"}, "default": []},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        handler=search_and_open,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="take_screenshot",
        description="截图并保存到桌面。",
        parameters={"type": "object", "properties": {}},
        handler=take_screenshot,
        safety_level="SAFE",
    ))

    # --- Filesystem (undoable) ---
    registry.register(ToolDefinition(
        name="fs_move",
        description="移动文件/文件夹到目标目录（可撤销，不会永久删除）。",
        parameters={
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "源路径"},
                "dest_dir": {"type": "string", "description": "目标目录"},
            },
            "required": ["src", "dest_dir"],
        },
        handler=fs_move,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="fs_rename",
        description="重命名文件/文件夹（可撤销，不会覆盖已有文件）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "路径"},
                "new_name": {"type": "string", "description": "新名称"},
            },
            "required": ["path", "new_name"],
        },
        handler=fs_rename,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="fs_write",
        description="写入文本到文件（可撤销：覆盖写会先备份）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入内容"},
            },
            "required": ["path", "content"],
        },
        handler=fs_write,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="fs_trash",
        description="将文件/文件夹移入废纸篓（可恢复）。这是删除类操作。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要移入废纸篓的路径"},
            },
            "required": ["path"],
        },
        handler=fs_trash,
        safety_level="DANGEROUS",
    ))

    registry.register(ToolDefinition(
        name="fs_undo_last",
        description="撤销最近一次文件操作（移动/重命名/写入/移入废纸篓）。",
        parameters={"type": "object", "properties": {}},
        handler=fs_undo_last,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="fs_search",
        description="全盘查找文件/文件夹（Spotlight）。用于‘帮我找…在哪’这类请求。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "名称关键词"},
                "kind": {"type": "string", "description": "any|file|dir", "default": "any"},
                "max_results": {"type": "integer", "description": "最大结果数", "default": 20},
                "scope": {"type": "array", "items": {"type": "string"}, "description": "可选：限制目录列表", "default": []},
            },
            "required": ["query"],
        },
        handler=fs_search,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="fs_preview",
        description="预览一组文件操作计划，不执行。",
        parameters={
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "description": "操作列表",
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "move"},
                                    "src": {"type": "string", "description": "源路径"},
                                    "dest_dir": {"type": "string", "description": "目标目录"},
                                },
                                "required": ["op", "src", "dest_dir"],
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "rename"},
                                    "path": {"type": "string", "description": "路径"},
                                    "new_name": {"type": "string", "description": "新名称"},
                                },
                                "required": ["op", "path", "new_name"],
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "write"},
                                    "path": {"type": "string", "description": "文件路径"},
                                    "content": {"type": "string", "description": "写入内容"},
                                },
                                "required": ["op", "path", "content"],
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "trash"},
                                    "path": {"type": "string", "description": "要移入废纸篓的路径"},
                                },
                                "required": ["op", "path"],
                            },
                        ]
                    },
                },
            },
            "required": ["ops"],
        },
        handler=fs_preview,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="fs_apply",
        description=(
            "执行一组文件操作计划（可撤销）。支持 move/rename/write/trash。"
            "注意：包含 trash 的计划属于删除类操作，会触发确认。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "description": "操作列表",
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "move"},
                                    "src": {"type": "string", "description": "源路径"},
                                    "dest_dir": {"type": "string", "description": "目标目录"},
                                },
                                "required": ["op", "src", "dest_dir"],
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "rename"},
                                    "path": {"type": "string", "description": "路径"},
                                    "new_name": {"type": "string", "description": "新名称"},
                                },
                                "required": ["op", "path", "new_name"],
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "write"},
                                    "path": {"type": "string", "description": "文件路径"},
                                    "content": {"type": "string", "description": "写入内容"},
                                },
                                "required": ["op", "path", "content"],
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "op": {"type": "string", "const": "trash"},
                                    "path": {"type": "string", "description": "要移入废纸篓的路径"},
                                },
                                "required": ["op", "path"],
                            },
                        ]
                    },
                },
            },
            "required": ["ops"],
        },
        handler=fs_apply,
        safety_level="SAFE",
    ))

    # --- System control (structured) ---
    registry.register(ToolDefinition(
        name="system_capabilities",
        description="查询当前系统控制能力与后端策略。",
        parameters={"type": "object", "properties": {}},
        handler=system_capabilities_tool,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="system_control",
        description=(
            "统一系统控制入口。用于音量/亮度/Wi-Fi/蓝牙/应用启动与退出。"
            "优先使用 Shortcuts（若存在），否则使用系统命令/脚本做最佳努力。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "volume|brightness|wifi|bluetooth|app"},
                "action": {"type": "string", "description": "up|down|mute|unmute|set|on|off|open|close"},
                "value": {"type": "string", "description": "可选：数值或应用名", "default": ""},
            },
            "required": ["target", "action"],
        },
        handler=system_control_tool,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="shortcuts_list",
        description="列出本机可用的 Apple Shortcuts。用于发现可复用的系统自动化能力。",
        parameters={"type": "object", "properties": {}},
        handler=shortcuts_list,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="shortcuts_run",
        description="运行一个 Apple Shortcut。优先用它来实现系统级动作（比 UI 自动化更稳定）。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Shortcut 名称"},
                "input_text": {"type": "string", "description": "可选输入文本", "default": ""},
            },
            "required": ["name"],
        },
        handler=shortcuts_run,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="shortcuts_view",
        description="在 Shortcuts App 中打开指定 Shortcut。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Shortcut 名称"},
            },
            "required": ["name"],
        },
        handler=shortcuts_view,
        safety_level="SAFE",
    ))

    registry.register(ToolDefinition(
        name="skills_save_local",
        description=(
            "保存一个本地 markdown 技能（SKILL.md）。"
            "用于把重复出现的工作流沉淀成可复用的技能模板。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能名称（建议小写短横线）"},
                "description": {"type": "string", "description": "一句话描述"},
                "body": {"type": "string", "description": "markdown 内容", "default": ""},
                "target_dir": {"type": "string", "description": "保存目录", "default": "~/.kage/skills"},
                "overwrite": {"type": "boolean", "description": "是否覆盖", "default": False},
            },
            "required": ["name", "description"],
        },
        handler=skills_save_local,
        safety_level="SAFE",
    ))

    # Optional MCP alias tools from config/mcp.json tool_map.
    _register_mcp_dynamic_aliases(registry)

    return registry

"""
Intent Keywords — shared heuristic intent classification.

Used by both server.py (_fast_command) and agentic_loop.py (_needs_tool_action)
to determine whether a user request likely needs tool execution.

Centralizing these patterns eliminates duplication and makes intent tuning
a single-point change.
"""

import re


# ---------------------------------------------------------------------------
# Tool-action intent patterns
# ---------------------------------------------------------------------------

_FILE_ACTION_PATTERNS = [
    r"整理|归档|移动|挪到|放到|改名|重命名|批量|文件夹|文件|目录|路径",
    r"查找文件|找一下文件|找个文件|搜索文件",
]

_WEB_INFO_PATTERNS = [
    r"查一下|搜一下|来源|是否真实|核实|辟谣|机票|价格|便宜",
    r"搜索|找一下|对比|便宜|价格|机票",
]

_SYSTEM_CONTROL_PATTERNS = [
    r"音量|亮度|wifi|wi-fi|蓝牙|bluetooth|打开应用|启动|关闭应用|退出",
]


def needs_tool_action(user_input: str) -> bool:
    """Heuristic: user request likely needs tools (file/web/system)."""
    s = str(user_input or "").strip()
    if not s:
        return False

    for pattern in _FILE_ACTION_PATTERNS:
        if re.search(pattern, s):
            return True
    for pattern in _WEB_INFO_PATTERNS:
        if re.search(pattern, s):
            return True
    for pattern in _SYSTEM_CONTROL_PATTERNS:
        if re.search(pattern, s, re.IGNORECASE):
            return True
    return False


def primitive_tool_hint(user_input: str) -> str:
    """Return a short hint about which primitive tool is most appropriate."""
    s = str(user_input or "").strip()
    low = s.lower()

    if re.search(r"整理|归档|移动|挪到|放到|改名|重命名|批量", s):
        return "fs_apply（批量 move/rename/write），必要时先 fs_preview"

    if re.search(r"找|查找|在哪|路径|目录|文件夹|文件", s):
        return "fs_search（全盘查找文件/文件夹）"

    if re.search(r"音量|亮度|wifi|wi-fi|蓝牙|bluetooth|打开应用|启动|关闭应用|退出", low, re.IGNORECASE):
        return "system_control（系统控制），如有现成 shortcut 可用 shortcuts_run"

    if re.search(r"打开.*网站|官网|网页|浏览器|打开.*\.(com|cn|net|org)", low):
        return "open_website 或 open_url"

    if re.search(r"查一下|搜一下|搜索|找一下|对比|便宜|价格|机票", s):
        return "smart_search / web_fetch / open_url"

    return "fs_search/fs_apply/system_control/open_url/smart_search（按需选择）"

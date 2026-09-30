"""Single source of truth for which tool schemas the model can see.

Why this module exists
----------------------
Tool pruning used to be a set of hardcoded name literals inlined in
``PromptBuilder._select_tool_names``. A tool that nobody remembered to add there was
silently invisible to the model on **every** route, while still being registered and
still being described to the model in prose. Two incidents:

  * ``search`` was pruned everywhere although the behaviour rule told the model to use
    it (found during the E0 review);
  * an audit of the shipped 34-tool registry found **six** tools unreachable on every
    route — including ``memory_search``, the memory-recall tool of an
    agent-memory project — because no route listed them.

The policy below makes visibility explicit and *total*:

  * each route has a baseline set, plus capability groups selected by intent keywords;
  * every registered tool must be classified; anything unclassified is **fail-open**
    (still offered to the model) so an omission can never silently remove a
    capability — and ``tests/test_tool_visibility.py`` fails while any tool stays
    unclassified, forcing a deliberate decision instead of an accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Route classification keywords (frozen for O(1) membership)
# ---------------------------------------------------------------------------
FILE_KEYWORDS = frozenset(
    ("文件", "目录", "文件夹", "路径", "代码", "项目", "仓库", "readme", ".py", ".ts", ".md")
)
SYSTEM_KEYWORDS = frozenset((
    "打开", "启动", "关闭", "调高", "调低", "音量", "亮度", "wifi", "蓝牙", "截图", "截屏",
    "截个图", "屏幕截图", "undo", "撤销", "太暗", "太亮", "太小声", "太大声", "太吵",
    "听不清", "看不清", "静音",
))
INFO_KEYWORDS = frozenset(
    ("天气", "新闻", "查", "搜索", "搜", "资料", "官网", "网页", "网站", "链接", "汇率", "股价", "价格", "机票")
)
WEB_KEYWORDS = frozenset(("天气", "新闻", "查", "搜索", "搜", "资料", "官网", "网页", "网站", "链接"))
OPEN_KEYWORDS = frozenset(("打开", "open", "launch"))
SYSTEM_CTRL_KEYWORDS = frozenset((
    "音量", "亮度", "wifi", "蓝牙", "静音", "截屏", "截图", "截个图", "屏幕截图", "screenshot",
))
SKILL_KEYWORDS = frozenset(("skill", "技能", "流程", "模板", "复用", "沉淀"))

# ---------------------------------------------------------------------------
# CORE: present on every route. Kept small — it is paid for on every request.
# Budget note: the prompt-resident surface should stay well under the 30-50 tool
# range where tool-selection accuracy degrades.
# ---------------------------------------------------------------------------
# Only registered in candidate-private experiment registries, not desktop defaults.
EXPERIMENT_SLOTS: frozenset[str] = frozenset({"skill_search", "skill_call"})

CORE: frozenset[str] = EXPERIMENT_SLOTS | frozenset({
    "get_time",
    "search",
    "smart_search",
    "web_fetch",
    "web_search",
    "memory_search",       # memory recall must always be reachable by the model
})

# BASE: CORE plus the tools any tool-requiring conversational turn may legitimately
# need, including the local skill reuse loop (find -> read -> save).
BASE: frozenset[str] = CORE | frozenset({
    "exec",
    "fs_search",
    "fs_preview",
    "fs_apply",
    "fs_undo_last",
    "system_control",
    "find_skills",
    "skills_read",
    "skills_save_local",
})

# Capability groups, selected by intent keywords on top of the route baseline.
GROUPS: dict[str, frozenset[str]] = {
    "web": frozenset({"tinyfish_search", "tavily_search", "search_and_open", "fetch_content"}),
    "browse": frozenset({"open_url", "open_website", "open_app"}),
    "files": frozenset({"fs_move", "fs_rename", "fs_write", "fs_trash"}),
    "system": frozenset({
        "system_capabilities", "take_screenshot",
        "shortcuts_list", "shortcuts_run", "shortcuts_view",
    }),
    "skills": frozenset({
        "find_skills", "skills_read", "skills_save_local",
        "skills_find_remote", "skills_list", "skills_install", "proactive_agent",
    }),
}

# Command route: the action surface (system/file/browse plus search, which the old
# hardcoded set forgot, so "查一下再整理成文件" could not search at all).
CMD_BASE: frozenset[str] = (BASE | GROUPS["browse"] | GROUPS["system"]) - {"take_screenshot"}

# Info route: minimal, search-only surface.
INFO_DEFAULT: tuple[str, ...] = tuple(sorted(CORE))
INFO_WEATHER: tuple[str, ...] = tuple(sorted(EXPERIMENT_SLOTS | {"smart_search", "web_fetch", "memory_search"}))

# Names the policy reserves for MCP aliases declared in config/mcp.json. They may not
# exist in the registry today (`_register_mcp_dynamic_aliases` does accept these names),
# so they are classified but not treated as "phantom" entries by the audit test.
ALIAS_SLOTS: frozenset[str] = frozenset({"web_search", "search_alias", "lookup"})

# Every name this policy can ever show. Used by the reachability invariant test.
CLASSIFIED: frozenset[str] = frozenset(
    set(CORE) | set(BASE) | set(CMD_BASE) | set(INFO_DEFAULT) | set(INFO_WEATHER)
    | set(ALIAS_SLOTS)
    | {name for group in GROUPS.values() for name in group}
)


@dataclass(frozen=True)
class VisibilityDecision:
    """Result of a visibility query."""

    names: tuple[str, ...]
    route: str
    unclassified: tuple[str, ...] = field(default=())

    @property
    def pruned(self) -> bool:
        return bool(self.names)


def _route_groups(route: str, text: str, groups: dict[str, frozenset[str]]) -> set[str]:
    """Capability groups activated by intent keywords for a route."""
    chosen: set[str] = set()
    is_web = any(k in text for k in WEB_KEYWORDS)
    is_open = any(k in text for k in OPEN_KEYWORDS)
    is_file = any(k in text for k in FILE_KEYWORDS)
    is_system = any(k in text for k in SYSTEM_CTRL_KEYWORDS)
    is_skill = any(k in text for k in SKILL_KEYWORDS)

    if route == "command":
        # Commands act on the machine: browsing is always in scope; the rest is
        # keyword-driven so a plain command does not carry a screenshot/UI surface.
        chosen |= groups["browse"]
    if is_file:
        chosen |= groups["files"]
    if is_system:
        chosen |= groups["system"]
    if is_open or is_web:
        chosen |= groups["browse"]
    if is_web:
        chosen |= groups["web"]
    if is_skill:
        chosen |= groups["skills"]
    return chosen


def select(
    user_input: str,
    route: str,
    registered: set[str] | frozenset[str] | None = None,
) -> VisibilityDecision:
    """Decide which tool names the model may see for this request.

    ``registered`` enables the fail-open guarantee: any registered tool the policy has
    not classified is still offered (and reported in ``unclassified``) so a missing
    entry degrades coverage instead of silently deleting a capability.
    """
    text = str(user_input or "").strip().lower()
    if not text:
        return VisibilityDecision((), route or "chat")

    route = route or "chat"

    if route == "info":
        names = set(INFO_WEATHER if "天气" in text else INFO_DEFAULT)
        # The info surface is intentionally minimal, but a *specific* intent (skills,
        # files, system) must not be swallowed by a stray search keyword: "帮我搜索并
        # 安装一个技能" classifies as info yet clearly needs the skill tools. Only the
        # generic web group is withheld here, so pure lookups stay minimal.
        names |= _route_groups(route, text, GROUPS) - set(GROUPS["web"]) - set(GROUPS["browse"])
    elif route == "command":
        names = set(CMD_BASE)
        names |= _route_groups(route, text, GROUPS)
    else:
        names = set(BASE)
        names |= _route_groups(route, text, GROUPS)

    unclassified: tuple[str, ...] = ()
    if registered:
        unknown = {str(n) for n in registered} - set(CLASSIFIED)
        if unknown:
            # Fail-open: never let a missing classification hide a capability.
            unclassified = tuple(sorted(unknown))
            names |= set(unclassified)

    # Weather answers inline: never hand the model a browser for it.
    if "天气" in text:
        names -= {"open_url", "open_website"}

    return VisibilityDecision(tuple(sorted(names)), route, unclassified)

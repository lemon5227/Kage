"""
Prompt Builder — 动态提示词构建 + 双通道工具呈现

按优先级组装系统提示词：
  身份(SOUL.md) > 用户信息(USER.md) > 当前时间 > 相关记忆 > 工具描述 > 历史

功能：
- 双通道工具呈现：系统提示词文本 + JSON Schema
- count_tokens: 计算 token 数（简单估算）
- token 预算管理：超过 80% 时从最旧历史开始移除
- 保证系统提示词 + 最近 3 轮历史不被截断
- 注入"先尝试自己解决"的行为准则
"""

import datetime
import logging
import time
from typing import Optional, TYPE_CHECKING

from core.trace import Span, log

if TYPE_CHECKING:
    from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# Approximate: 1 token ≈ 1.5 Chinese chars or 4 English chars
_AVG_CHARS_PER_TOKEN = 3

# Keyword sets for route classification (frozen for O(1) membership + no rebuild)
# Visibility policy (which tool schemas the model may see) lives in core.tool_visibility;
# the frozensets below are derived aliases kept for import compatibility and tests.
from core.tool_visibility import (
    BASE as _VIS_BASE,
    FILE_KEYWORDS,
    INFO_KEYWORDS,
    OPEN_KEYWORDS,
    SYSTEM_CTRL_KEYWORDS,
    SYSTEM_KEYWORDS,
    WEB_KEYWORDS,
    CMD_BASE as _VIS_CMD_BASE,
    CORE as _VIS_CORE,
    GROUPS as _VIS_GROUPS,
    select as _select_visibility,
)

# Keyword sets are owned by core.tool_visibility (single source of truth for both
# route classification and capability-group activation). The underscore-prefixed
# aliases remain for import compatibility.
_FILE_KEYWORDS = FILE_KEYWORDS
_SYSTEM_KEYWORDS = SYSTEM_KEYWORDS
_INFO_KEYWORDS = INFO_KEYWORDS
_WEB_KEYWORDS = WEB_KEYWORDS
_OPEN_KEYWORDS = OPEN_KEYWORDS
_SYSTEM_CTRL_KEYWORDS = SYSTEM_CTRL_KEYWORDS

# Tool-name sets now live in core.tool_visibility (single source of truth). No
# compatibility aliases are kept here: they had become dead names that could drift
# from the policy, which is exactly how tools silently disappeared before.
class PromptBuilder:
    """动态提示词组装，管理 token 预算，双通道工具呈现"""

    BEHAVIOR_RULE = (
        "行为准则：遇到问题先尝试自己解决（搜索、换工具、换参数），"
        "只在尝试至少一种方案后仍无法完成时才告知用户。"
        "如果不确定是否有现成流程模板/技能可复用，先调用 skills_find_remote 搜索 skills.sh 生态。"
        "涉及文件操作时，优先输出结构化计划并使用 fs_apply 执行（move/rename/write）。"
        "除非用户明确要求删除，否则不要使用 trash/删除类操作。"
        "当用户提出明显需要工具的请求（找文件/整理/打开/搜索/核验等）时，不要闲聊，优先调用工具。"
        "当用户只是想获得信息（例如天气/百科/新闻摘要）时，优先使用 smart_search + web_fetch 直接给出结论，"
        "不要打开浏览器，除非用户明确要求‘打开网页/在浏览器里看’。"
        "涉及 macOS 系统级动作时，如果本机存在对应 Shortcut 则优先 shortcuts_run；否则直接用 system_control 的 fallback。"
        "如果用户重复请求同一个可工具化的流程，考虑调用 skills_save_local 保存为本地技能文件以便复用。"
    )

    COMMAND_RULE = (
        "命令模式：优先直接调用工具，不要闲聊；"
        "涉及系统动作优先 system_control/shortcuts_run；"
        "除非用户明确要求删除，否则不要使用 trash/删除类操作。"
    )

    INFO_RULE = (
        "信息模式：优先用 smart_search/web_fetch 获取事实并直接给出结论；"
        "不要打开浏览器，除非用户明确要求‘打开网页/在浏览器里看’；"
        "信息不足时明确说明缺失项。"
    )

    CHAT_RULE = (
        "对话模式：简洁自然回应；"
        "若用户请求可工具化任务，优先转为工具调用而不是闲聊。"
    )

    def __init__(
        self,
        identity_store,
        memory_system,
        tool_registry: "ToolRegistry",
        max_context_tokens: int = 4096,
        memory_cfg: Optional[dict] = None,
        prune_tools: bool = False,
        memory_profile=None,
    ):
        self.identity = identity_store
        self.memory = memory_system
        self.registry = tool_registry
        self.max_context_tokens = max_context_tokens
        self.memory_cfg = memory_cfg or {}
        self.prune_tools = bool(prune_tools)
        self.last_route: str = "chat"
        self.profile = memory_profile
        # Names already reported as unclassified (warn once, not every request).
        self._warned_unclassified: set[str] = set()

    def classify_route(self, user_input: str) -> str:
        """Classify request into command/info/chat for routing."""
        text = str(user_input or "").strip().lower()
        if not text:
            return "chat"

        has_file = any(k in text for k in _FILE_KEYWORDS)
        has_system = any(k in text for k in _SYSTEM_KEYWORDS)
        has_info = any(k in text for k in _INFO_KEYWORDS)

        if text.startswith("/") or has_file or has_system:
            return "command"
        if has_info:
            return "info"
        return "chat"

    def _select_tool_names(self, user_input: str, route: str = "") -> list[str] | None:
        """Tool names the model may see for this request (see core.tool_visibility).

        Returns None when the request is empty, which disables pruning entirely.
        Any registered tool the policy has not classified is still returned
        (fail-open) and logged, so an omission cannot silently hide a capability.
        """
        text = str(user_input or "").strip().lower()
        if not text:
            return None

        route = route or self.classify_route(text)
        registered = set(self.registry.get_tool_names()) if self.registry else set()
        decision = _select_visibility(text, route, registered)
        newly_unclassified = [n for n in decision.unclassified
                             if n not in self._warned_unclassified]
        if newly_unclassified:
            self._warned_unclassified.update(newly_unclassified)
            logger.warning(
                "tool visibility: %d registered tool(s) not classified by the policy, "
                "offering them anyway (fail-open): %s. Add them to core.tool_visibility "
                "so their visibility is deliberate.",
                len(newly_unclassified), ", ".join(newly_unclassified),
            )
        return list(decision.names)

    def build(
        self,
        user_input: str,
        history: list[dict],
        current_emotion: str = "neutral",
    ) -> tuple[list[dict], list[dict]]:
        """Assemble the full message list and tool schemas.

        Priority: identity > user info > time > memory > tools > history.
        Guarantees: system prompt + last 3 history turns are never truncated.
        
        Returns:
            tuple: (messages, tool_schemas)
                - messages: 消息列表
                - tool_schemas: OpenAI Function Calling 格式的工具 Schema 列表
        """
        # 1. System prompt sections (in order)
        soul = str(self.identity.load_soul() or "")
        user_info = ""
        if hasattr(self.identity, "get_unified_user_context"):
            try:
                res = self.identity.get_unified_user_context(self.profile)
                if isinstance(res, str):
                    user_info = res
                else:
                    user_info = str(self.identity.load_user() or "")
            except Exception:
                user_info = str(self.identity.load_user() or "")
        else:
            user_info = str(self.identity.load_user() or "")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

        span = Span("prompt", "build", user_len=len(str(user_input or "")), history=len(history or []))
        route = self.classify_route(user_input)
        self.last_route = route
        log("prompt", "route", route=route)

        # Tool schemas (optionally pruned to reduce latency)
        tool_schemas: list[dict] = []
        if self.registry:
            try:
                tool_schemas = self.registry.get_all_schemas()
            except Exception:
                tool_schemas = []

        log("prompt", "tools.schemas", count=len(tool_schemas))

        if self.prune_tools and tool_schemas:
            allow = self._select_tool_names(user_input, route=route)
            if allow:
                allow_set = set(allow)
                tool_schemas = [
                    s
                    for s in tool_schemas
                    if isinstance(s, dict)
                    and s.get("type") == "function"
                    and isinstance(s.get("function"), dict)
                    and str(s["function"].get("name") or "") in allow_set
                ]
        log("prompt", "tools.schemas_pruned", count=len(tool_schemas))

        # Detect broad intent for context trimming.
        is_web_like = route == "info"
        is_command_like = route == "command"

        # Recall relevant memories (configurable for speed)
        memories = []
        if user_input.strip():
            try:
                t_mem = time.monotonic()
                recall_enabled = bool(self.memory_cfg.get("recall_enabled", True))
                vector_weight = float(self.memory_cfg.get("vector_weight", 0.7))
                bm25_weight = float(self.memory_cfg.get("bm25_weight", 0.3))

                # For pure web/info requests, skip memory recall by default to reduce latency.
                if is_web_like:
                    recall_enabled = bool(self.memory_cfg.get("recall_web_enabled", False))

                # For command-like requests (file/system/open/run), memory is usually noise.
                # Force disabled for speed/reliability.
                if is_command_like:
                    recall_enabled = False

                if not recall_enabled:
                    memories = []
                elif vector_weight <= 0:
                    memories = self.memory.bm25_search(user_input, n_results=5)
                elif bm25_weight <= 0:
                    memories = self.memory.vector_search(user_input, n_results=5)
                else:
                    memories = self.memory.recall(user_input, n_results=5)
                log(
                    "prompt",
                    "memory.recall",
                    enabled=recall_enabled,
                    vector_weight=vector_weight,
                    bm25_weight=bm25_weight,
                    results=len(memories or []),
                    elapsed_ms=f"{(time.monotonic()-t_mem)*1000:.1f}",
                )
            except Exception as exc:
                logger.warning("Memory recall failed: %s", exc)

        memory_text = ""
        if memories:
            lines = [f"- {m['content']}" for m in memories]
            memory_text = "相关记忆:\n" + "\n".join(lines)

        # Tool text: keep it short (schemas are passed separately)
        tools_text = ""
        if tool_schemas:
            try:
                names = []
                for s in tool_schemas:
                    fn = (s or {}).get("function") if isinstance(s, dict) else None
                    if isinstance(fn, dict) and fn.get("name"):
                        names.append(str(fn.get("name")))
                if names:
                    tools_text = "可用工具(精简): " + ", ".join(names)
            except Exception:
                tools_text = ""

        # Assemble system prompt
        system_parts = [soul, user_info, f"当前时间: {now}"]

        # Inject user profile summary if available
        if self.profile:
            profile_summary = self.profile.get_profile_summary()
            if profile_summary.strip():
                system_parts.append(f"【用户档案】\n{profile_summary}")

        if memory_text:
            system_parts.append(memory_text)
        if tools_text:
            system_parts.append(tools_text)
        # Keep global baseline rule so existing behaviors/tests remain stable,
        # then append route-specific concise rule.
        system_parts.append(self.BEHAVIOR_RULE)
        if route == "command":
            system_parts.append(self.COMMAND_RULE)
        elif route == "info":
            system_parts.append(self.INFO_RULE)
        elif route == "chat":
            system_parts.append(self.CHAT_RULE)
        system_content = "\n\n".join(str(p) for p in system_parts if str(p).strip())

        # 2. Build messages
        messages = [{"role": "system", "content": system_content}]

        # Add history (will be trimmed if needed)
        history_in = list(history or [])
        # For web/info requests, keep a smaller rolling history window for speed.
        if route == "info" and len(history_in) > 8:
            history_in = history_in[-8:]
        elif route == "command" and len(history_in) > 10:
            history_in = history_in[-10:]
        elif route == "chat" and len(history_in) > 16:
            history_in = history_in[-16:]
        for turn in history_in:
            messages.append({"role": turn["role"], "content": turn["content"]})

        # Add current user input
        messages.append({"role": "user", "content": user_input})

        # 3. Token budget enforcement
        budget = int(self.max_context_tokens * 0.8)
        messages = self._enforce_budget(messages, budget)

        total_tokens = self.count_tokens(messages)
        logger.debug("Prompt built: %d tokens (budget %d)", total_tokens, budget)

        span.end(tokens=total_tokens, tools=len(tool_schemas))

        return messages, tool_schemas

    def count_tokens(self, messages: list[dict]) -> int:
        """Estimate token count for a message list."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return max(1, total_chars // _AVG_CHARS_PER_TOKEN)

    def _enforce_budget(self, messages: list[dict], budget: int) -> list[dict]:
        """Remove oldest history turns until within budget.

        Preserves: system prompt (index 0) + last 3 conversation turns + current user input.
        """
        # Track per-message token counts so we can update the running total
        # incrementally instead of summing from scratch each pop (was O(n^2)).
        per_msg = [
            max(1, len(m.get("content", "")) // _AVG_CHARS_PER_TOKEN)
            for m in messages
        ]
        total = sum(per_msg)
        if total <= budget:
            return messages

        # messages = [system, ...history..., current_user_input]
        # Protect: system (0), last 3 history turns before user input, and user input (-1)
        if len(messages) <= 5:
            # system + up to 3 history + user input — can't trim further
            return messages

        # Remove from index 1 (oldest history) until budget met
        while len(messages) > 5 and total > budget:
            removed = per_msg.pop(1)
            messages.pop(1)
            total -= removed

        return messages

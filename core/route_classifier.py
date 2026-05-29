"""
Route Classifier — intent routing for user input.

Classifies user input into one of three routes:
- command: execute actions / system control
- info: query information (weather, search, etc.)
- chat: casual conversation

Uses rule-first classification with optional model assist for ambiguity.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Route keywords
# ---------------------------------------------------------------------------

_SYSTEM_KEYWORDS = ("打开", "关闭", "调高", "调低", "音量", "亮度", "wifi", "蓝牙")
_INFO_KEYWORDS = ("查", "搜索", "搜", "天气", "新闻", "价格", "汇率", "视频")
_TOOLISH_KEYWORDS = (
    "打开", "关闭", "启动", "开启", "退出",
    "查询", "查", "搜索", "搜", "找", "推荐",
    "下载", "安装",
    "截图", "截屏",
    "音量", "亮度", "wifi", "蓝牙",
    "网址", "链接", "网站", "网页",
)
_EXPLICIT_HELP = ("帮我", "请帮", "麻烦", "给我", "能不能")
_ENGLISH_TOOLISH = ("open ", "close ", "search", "download", "install", "url", "link")

_ROUTE_SYSTEM_P = (
    "你是路由分类器。只输出一个词：command 或 info 或 chat。"
    "command=执行动作/系统控制；info=查询信息；chat=闲聊。"
)


def classify_route(user_input: str, prompt_builder_route: str = "chat") -> str:
    """Rule-first route classification.

    Args:
        user_input: The user's input text.
        prompt_builder_route: The base route from prompt_builder (default: "chat").

    Returns:
        One of "command", "info", or "chat".
    """
    return prompt_builder_route


def is_route_ambiguous(user_input: str, base_route: str) -> bool:
    """Check if the route classification is ambiguous."""
    s = str(user_input or "").strip().lower()
    if not s:
        return False
    has_system = any(k in s for k in _SYSTEM_KEYWORDS)
    has_info = any(k in s for k in _INFO_KEYWORDS)
    if base_route == "chat":
        return has_system or has_info
    if base_route == "command" and has_info:
        return sum(1 for k in _INFO_KEYWORDS if k in s) >= 2
    if base_route == "info" and has_system:
        return sum(1 for k in _SYSTEM_KEYWORDS if k in s) >= 2
    return False


def should_try_tools(user_input: str) -> bool:
    """Heuristic: route to action mode so the LLM can choose tools."""
    text = (user_input or "").strip()
    if not text:
        return False
    lower_text = text.lower()

    if any(tok in text for tok in _EXPLICIT_HELP):
        return True
    if any(tok in text for tok in _TOOLISH_KEYWORDS):
        return True
    if any(tok in lower_text for tok in _ENGLISH_TOOLISH):
        return True
    return False


def classify_route_by_model(user_input: str, model_provider) -> str:
    """Use lightweight model call for ambiguous route classification.

    Args:
        user_input: The user's input text.
        model_provider: A model provider with generate() method.

    Returns:
        One of "command", "info", or "chat".
    """
    user = f"用户输入：{str(user_input or '').strip()}\n只输出一个词。"
    try:
        resp = model_provider.generate(
            messages=[{"role": "system", "content": _ROUTE_SYSTEM_P}, {"role": "user", "content": user}],
            tools=None,
            max_tokens=8,
            temperature=0.0,
        )
        text = str(getattr(resp, "text", "") or "").strip().lower()
        if "command" in text:
            return "command"
        if "info" in text:
            return "info"
    except Exception as exc:
        logger.debug("Route classification by model failed: %s", exc)
    return "chat"

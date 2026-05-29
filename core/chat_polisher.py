"""
Chat Polisher — response cleaning, filtering, and polishing.

Centralizes all post-processing of chat responses before they are
spoken or sent to the frontend. Extracted from KageServer to reduce
the god-class burden and make text cleaning independently testable.
"""

import re

from core.response_sanitizer import sanitize_for_speech_text, strip_reasoning_artifacts


# ---------------------------------------------------------------------------
# Blocked words / phrases that leak from model output
# ---------------------------------------------------------------------------

_BLOCKED_WORDS = ["neutral", "happy", "sad", "angry", "fear", "surprised"]

_BLOCKED_PHRASES = [
    "AIspeak",
    "cant be",
    "AIspeak cant be",
    "<system-reminder>",
    "system-reminder",
    "<|system|>",
    "<|user|>",
    "<|assistant|>",
    "】",
    "【",
    "系统提示",
    "提示词",
    "文件工具哒",
    "工具哒",
]

# Maximum chat response length (truncated to fit avatar text bubble)
_MAX_CHAT_RESPONSE_LEN = 40

_ALLOWED_EMOJI = {"✨", "😤", "💖"}
_ALLOWED_PUNCT = set("，。！？!?、,.~:：;；()（）[]【】")

# Precompiled regex for blocked content removal (single pass)
_BLOCKED_RE = re.compile("|".join(
    re.escape(w) for w in _BLOCKED_WORDS + _BLOCKED_PHRASES
))

# Precompiled patterns for polish_chat_response
_RE_USER_ASSISTANT_ECHO = re.compile(r"用户[：:]\s*.*?助手[：:]\s*")
_RE_USER_LINE = re.compile(r"^用户[：:]\s*.*$", re.MULTILINE)
_RE_CAPABILITY_BRAG = re.compile(r"我能做[^。！？!]*[。！？!]*")
_RE_ITEM_COUNT = re.compile(r"\d+\s*项\s*事\s*[:：]\s*")
_RE_ITEM_LABEL = re.compile(r"项\s*事\s*[:：]\s*")
_RE_TRAILING_FILLER = re.compile(r"\s*[哒捏哇]+\s*(?:[!！。.]*)\s*$")
_RE_LEADING_DECO = re.compile(r"^[\s✨😤💖]+")


def filter_chat_text(text: str) -> str:
    """Remove blocked words, phrases, and disallowed characters."""
    if not text:
        return text

    text = _BLOCKED_RE.sub("", text)

    output = []
    for ch in text:
        code = ord(ch)
        if ch in _ALLOWED_EMOJI or ch in _ALLOWED_PUNCT:
            output.append(ch)
        elif ch.isalnum() or ch.isspace() or 0x4E00 <= code <= 0x9FFF:
            output.append(ch)
    return "".join(output)


# Pre-compiled regex for collapse_repeats: matches 3+ consecutive identical chars
_REPEAT_RE = re.compile(r"(.)\1{2,}")


def collapse_repeats(text: str) -> str:
    """Collapse consecutive repeated characters to at most 2 in a row."""
    if not text:
        return text
    return _REPEAT_RE.sub(r"\1\1", text)


def polish_chat_response(text: str) -> str:
    """Full post-processing pipeline for chat responses.

    Steps:
    1. Strip reasoning artifacts
    2. Normalize whitespace
    3. Strip user/assistant echo patterns
    4. Strip system/runtime artifacts
    5. Normalize addressing (Master → 你)
    6. Remove capability brag / meta descriptions
    7. Filter blocked words/characters
    8. Collapse repeated characters
    9. Strip trailing filler particles
    10. Strip leading decorative marks
    11. Truncate to 40 chars
    """
    if not text:
        return text

    cleaned = strip_reasoning_artifacts(text)
    cleaned = " ".join(cleaned.split())

    # Strip user/assistant echo patterns
    cleaned = _RE_USER_ASSISTANT_ECHO.sub("", cleaned)
    cleaned = _RE_USER_LINE.sub("", cleaned)

    # Strip system/runtime artifacts
    cleaned = sanitize_for_speech_text(cleaned)
    for marker in ["Master心情:", "Master心情", "Master 心情:", "Master 心情", "@@@"]:
        cleaned = cleaned.replace(marker, "")

    # Normalize addressing
    cleaned = cleaned.replace("Master", "你")

    # Remove capability brag / meta descriptions
    cleaned = _RE_CAPABILITY_BRAG.sub("", cleaned)
    cleaned = _RE_ITEM_COUNT.sub("", cleaned)
    cleaned = _RE_ITEM_LABEL.sub("", cleaned)

    # Filter blocked content
    cleaned = filter_chat_text(cleaned)
    cleaned = collapse_repeats(cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        cleaned = "嗯"

    # Strip trailing filler particles
    cleaned = _RE_TRAILING_FILLER.sub("", cleaned).strip()

    # Strip leading decorative marks
    cleaned = _RE_LEADING_DECO.sub("", cleaned).strip()

    if not cleaned:
        cleaned = "嗯"

    # Truncate
    if len(cleaned) > _MAX_CHAT_RESPONSE_LEN:
        cleaned = cleaned[:_MAX_CHAT_RESPONSE_LEN]

    return cleaned


def infer_chat_topic(text: str) -> str:
    """Infer the topic of a chat message for structured followups."""
    t = (text or "").strip()
    if not t:
        return ""
    if "朋友圈" in t or "发这条" in t:
        return "moments"
    if "怎么回" in t:
        return "reply"
    if "道歉" in t:
        return "apology"
    if any(k in t for k in ["怎么弄", "怎么做", "怎么搞"]):
        return "howto"
    if "今天晚上" in t or "今晚" in t:
        return "tonight"
    return ""


def structured_chat_followup(topic: str, user_input: str) -> str | None:
    """Rule-based followups for product-grade reliability."""
    text = (user_input or "").strip()
    if not text:
        return None

    if topic == "moments":
        audience = "同学" if "同学" in text else "朋友" if "朋友" in text else "大家"
        if "考完" in text or "考试" in text:
            caption = "考试终于结束啦，辛苦自己了。接下来好好休息一下。"
        else:
            caption = f"{text}"
            if len(caption) < 8:
                caption = f"{caption}。"
        return f"建议发给{audience}。文案：{caption}"

    if topic == "apology":
        return "你可以这样说：刚刚我语气有点冲，对不起。我很在乎你，想好好说。"

    if topic == "reply":
        return "把对方原话贴我，我给你拟一句更贴合的回复。"

    if topic == "howto":
        return "你先告诉我：你现在卡在哪一步、目标是什么？"

    if topic == "tonight":
        return "你是想问天气，还是今晚的安排？"

    return None

from __future__ import annotations

from dataclasses import dataclass
import re

from core.agentic_loop import AgenticLoop


@dataclass(frozen=True)
class RealtimeTaskClass:
    lane: str
    reason: str
    can_background: bool


@dataclass(frozen=True)
class RealtimeCommandDecision:
    mode: str  # execute|confirm|ignore
    tool_name: str = ""
    arguments: dict | None = None
    confidence: float = 0.0
    intent_description: str = ""


@dataclass(frozen=True)
class PendingCommandResolution:
    action: str  # execute|cancel|fallback
    corrected_text: str = ""


def classify_realtime_task(user_input: str) -> RealtimeTaskClass:
    text = str(user_input or "").strip()
    low = text.lower()
    if not text:
        return RealtimeTaskClass(lane="chat", reason="empty", can_background=False)

    if is_confirm_text(text) or is_cancel_text(text):
        return RealtimeTaskClass(lane="realtime", reason="confirmation", can_background=False)

    if "天气" in text and not any(k in text for k in ("打开", "浏览器", "网页", "网站")):
        return RealtimeTaskClass(lane="realtime", reason="weather_fastpath", can_background=False)

    if "视频" in text or any(k in low for k in ("youtube", "youtuber", "video", "bilibili")):
        return RealtimeTaskClass(lane="realtime", reason="video_fastpath", can_background=False)

    call, confidence = AgenticLoop._infer_command_tool_call_scored(text)
    if isinstance(call, dict) and call.get("name") and confidence >= 0.5:
        return RealtimeTaskClass(lane="realtime", reason="command_fastpath", can_background=False)

    if any(k in text for k in ("整理桌面", "整理下载", "批量", "归类", "总结", "分析")):
        return RealtimeTaskClass(lane="background", reason="multi_step_or_long_task", can_background=True)

    return RealtimeTaskClass(lane="agent", reason="general_case", can_background=True)


def decide_realtime_command(user_input: str) -> RealtimeCommandDecision:
    call, confidence = AgenticLoop._infer_command_tool_call_scored(user_input)
    if not isinstance(call, dict) or not call.get("name"):
        return RealtimeCommandDecision(mode="ignore")

    tool_name = str(call.get("name") or "")
    arguments = dict(call.get("arguments") or {})
    if confidence >= 0.9:
        return RealtimeCommandDecision(
            mode="execute",
            tool_name=tool_name,
            arguments=arguments,
            confidence=float(confidence),
            intent_description=describe_command_intent(tool_name, arguments),
        )
    if confidence >= 0.5:
        return RealtimeCommandDecision(
            mode="confirm",
            tool_name=tool_name,
            arguments=arguments,
            confidence=float(confidence),
            intent_description=describe_command_intent(tool_name, arguments),
        )
    return RealtimeCommandDecision(mode="ignore")


def resolve_pending_inferred_command(tool_name: str, arguments: dict, text: str) -> PendingCommandResolution:
    raw = str(text or "").strip()
    corrected = extract_correction_text(raw)
    if is_confirm_text(raw):
        return PendingCommandResolution(action="execute")
    if is_cancel_text(raw) and not corrected:
        return PendingCommandResolution(action="cancel")
    if corrected:
        return PendingCommandResolution(action="fallback", corrected_text=corrected)
    return PendingCommandResolution(action="fallback")


def is_confirm_text(text: str) -> bool:
    s = str(text or "").strip().lower()
    return s in ("确认", "确定", "好", "行", "执行", "是", "ok", "okay", "yes") or ("确认" in s)


def is_cancel_text(text: str) -> bool:
    s = str(text or "").strip().lower()
    return s in ("取消", "算了", "不", "不要", "no", "nope") or ("取消" in s)


def extract_correction_text(text: str) -> str:
    s = str(text or "").strip()
    m = re.search(r"不是这个\s*[，,]?\s*是\s*(.+)$", s)
    if m:
        return str(m.group(1) or "").strip(" ，,。.!！？?；;:：")
    return ""


def describe_command_intent(name: str, args: dict) -> str:
    n = str(name or "").strip()
    a = args if isinstance(args, dict) else {}
    if n == "system_control":
        target = str(a.get("target") or "").strip().lower()
        action = str(a.get("action") or "").strip().lower()
        if target == "brightness":
            return "调高亮度" if action == "up" else "调低亮度"
        if target == "volume":
            if action == "mute":
                return "静音"
            return "调高音量" if action == "up" else "调低音量"
        if target == "wifi":
            return "打开 Wi-Fi" if action == "on" else "关闭 Wi-Fi"
        if target == "bluetooth":
            return "打开蓝牙" if action == "on" else "关闭蓝牙"
    return "执行系统操作"

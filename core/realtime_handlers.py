from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core.realtime_lane import extract_correction_text, is_cancel_text, is_confirm_text


@dataclass(frozen=True)
class VideoFollowupEarlyAction:
    consume_turn: bool = False
    clear_pending: bool = False
    speech: str = ""
    corrected_input: str = ""


def is_video_intent(text: str) -> bool:
    s = str(text or "")
    low = s.lower()
    return ("视频" in s) or any(k in low for k in ("youtube", "youtuber", "video", "bilibili")) or any(
        k in s for k in ("b站", "哔哩", "哔哩哔哩")
    )


def normalize_video_query_for_search(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    s = s.strip(" ，,。.!！？?；;:：")
    s = re.sub(
        r"[，,\s]*(然后|再|并且|并|顺便)\s*(把|帮我)?\s*(它|这个|结果|视频|链接)?\s*(打开|点开|播放|播一下|放一下)(吧|一下)?[。.!！？?]*\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"[，,\s]*(把|帮我)?\s*(它|这个|结果|视频|链接)?\s*(打开|点开|播放|播一下|放一下)(吧|一下)?[。.!！？?]*\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"[，,\s]*(然后|再|并且|并|顺便)\s*打开[。.!！？?]*\s*$", "", s, flags=re.IGNORECASE)
    return s.strip(" ，,。.!！？?；;:：")


def extract_video_subject(text: str) -> str:
    s = normalize_video_query_for_search(text)
    if not s:
        return ""
    s = re.sub(r"^不是这个\s*[，,]?\s*是\s*", "", s)
    s = re.sub(r"^(帮我|请|麻烦|请帮我|我想|我想看|帮忙)\s*", "", s)
    s = re.sub(r"^(找|搜|搜索|查|看)(一下|下)?\s*", "", s)
    s = s.strip(" ，,。.!！？?；;:：")
    s = re.sub(r"\s*(的)?\s*(最新|最近|刚发|本周|今日)?\s*(视频|频道|直播)\s*$", "", s)
    s = re.sub(r"\s*(在)?\s*(youtube|bilibili|油管|b站|哔哩哔哩)\s*(上)?\s*$", "", s, flags=re.IGNORECASE)
    return s.strip(" ，,。.!！？?；;:：")


def video_selection_evidence(subject: str, item: dict) -> dict[str, bool]:
    subj = str(subject or "").strip().lower()
    title = str((item or {}).get("title") or "").strip().lower()
    channel = str((item or {}).get("snippet") or "").strip().lower()
    url = str((item or {}).get("url") or "").strip().lower()
    return {
        "subject_in_title": bool(subj and subj in title),
        "subject_in_channel": bool(subj and subj in channel),
        "youtube_domain": ("youtube.com" in url) or ("youtu.be" in url),
        "bilibili_domain": ("bilibili.com" in url),
    }


def format_video_evidence(ev: dict[str, bool]) -> str:
    if not isinstance(ev, dict):
        return ""
    reasons = []
    if ev.get("subject_in_channel"):
        reasons.append("频道名命中")
    if ev.get("subject_in_title"):
        reasons.append("标题命中")
    if ev.get("youtube_domain"):
        reasons.append("YouTube来源")
    if ev.get("bilibili_domain"):
        reasons.append("B站来源")
    if not reasons:
        return ""
    return f"依据：{'、'.join(reasons)}。"


def video_subject_tokens(subject: str) -> list[str]:
    s = str(subject or "").strip().lower()
    if not s:
        return []
    parts = [p for p in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", s) if p]
    out: list[str] = []
    for p in parts:
        if re.search(r"[\u4e00-\u9fff]", p):
            if len(p) >= 1:
                out.append(p)
        elif len(p) >= 3:
            out.append(p)
    return out[:8]


def video_subject_match_score(subject: str, item: dict) -> float:
    subj = str(subject or "").strip().lower()
    if not subj:
        return 0.0
    title = str((item or {}).get("title") or "").strip().lower()
    channel = str((item or {}).get("snippet") or "").strip().lower()
    hay = f"{title} {channel}".strip()
    if not hay:
        return 0.0
    if subj in hay:
        return 10.0
    score = 0.0
    for tok in video_subject_tokens(subj):
        if tok and tok in hay:
            score += 2.5 if re.search(r"[\u4e00-\u9fff]", tok) else 1.5
    return score


def is_backchannel_text(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return True
    tiny = {
        "嗯", "嗯嗯", "啊", "哦", "噢", "额", "呃", "诶", "欸", "哎", "唉",
        "好的", "好吧", "行", "行吧", "可以", "知道了", "收到", "ok", "okay",
    }
    return s in tiny


def wants_open_video_action(text: str) -> bool:
    s = str(text or "").strip().lower()
    return bool(s) and any(k in s for k in ("打开", "点开", "播放", "播一下", "放一下", "open", "play"))


def is_open_only_followup_text(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    if extract_correction_text(s):
        return False
    if is_confirm_text(s) or is_cancel_text(s):
        return False
    open_tokens = ("打开", "点开", "播放", "播一下", "放一下", "open", "play", "就这个", "这个")
    return any(tok in s for tok in open_tokens)


def extract_video_followup_correction_text(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    if is_backchannel_text(s):
        return ""
    explicit = extract_correction_text(s)
    if explicit:
        return explicit
    s = s.strip(" ，,。.!！？?；;:：")
    m = re.match(r"^(?:就?是)\s*(.+)$", s)
    if m:
        cand = str(m.group(1) or "").strip(" ，,。.!！？?；;:：")
        if is_backchannel_text(cand):
            return ""
        return cand
    if is_confirm_text(s) or is_cancel_text(s):
        return ""
    if len(s) <= 24 and len(s) >= 2 and not any(
        k in s for k in ("帮我", "请", "打开", "调高", "调低", "天气", "音量", "亮度", "蓝牙", "Wi-Fi", "wifi")
    ):
        return s
    return ""


def preprocess_video_followup_turn(text: str) -> VideoFollowupEarlyAction:
    raw = str(text or "").strip()
    if not raw:
        return VideoFollowupEarlyAction()
    if is_cancel_text(raw):
        return VideoFollowupEarlyAction(
            consume_turn=True,
            clear_pending=True,
            speech="好，那我先不继续找。",
        )
    corrected = extract_video_followup_correction_text(raw)
    if not corrected:
        return VideoFollowupEarlyAction()

    normalized = normalize_video_query_for_search(corrected) or corrected
    low = normalized.lower()
    if not (
        ("视频" in normalized)
        or any(k in low for k in ("youtube", "youtuber", "video", "bilibili"))
        or any(k in normalized for k in ("b站", "哔哩", "哔哩哔哩"))
    ):
        normalized = f"{normalized} 最新视频"
    return VideoFollowupEarlyAction(
        clear_pending=True,
        corrected_input=normalized,
    )


async def weather_fastpath(
    user_input: str,
    *,
    agentic_loop: Any,
    get_fast_cache: Callable[[str, int], Any],
    set_fast_cache: Callable[[str, str], None],
    fetch_open_meteo: Callable[[str, int], str],
    fetch_metno: Callable[[str], str],
    fetch_weather_tool_call_quick: Callable[[str], dict | None],
    log_fn: Callable[..., None],
) -> str:
    city_raw = agentic_loop._extract_weather_city(str(user_input))
    day_offset = agentic_loop._extract_weather_day_offset(str(user_input))
    city = agentic_loop._normalize_city_for_weather_api(city_raw)
    cache_key = f"weather_fast:{str(city_raw).strip().lower()}:{int(day_offset)}"
    cached = get_fast_cache(cache_key, 120)
    if cached:
        return str(cached)

    providers_env = str(os.environ.get("KAGE_WEATHER_PROVIDERS", "open_meteo,metno")).strip()
    providers = [p.strip().lower() for p in providers_env.split(",") if p.strip()]
    if not providers:
        providers = ["open_meteo", "metno"]
    providers = providers[:2]

    async def _run_provider(name: str) -> tuple[str, str]:
        if name == "open_meteo":
            out = await asyncio.to_thread(fetch_open_meteo, city, day_offset)
            return (name, str(out or ""))
        if name == "wttr":
            tc = await asyncio.to_thread(fetch_weather_tool_call_quick, city)
            if isinstance(tc, dict):
                concise = agentic_loop._format_weather_from_wttr_result(tc, city_raw, day_offset)
                return (name, str(concise or ""))
            return (name, "")
        if name == "metno":
            out = await asyncio.to_thread(fetch_metno, city)
            return (name, str(out or ""))
        return (name, "")

    tasks = [asyncio.create_task(_run_provider(p)) for p in providers]
    best_text = ""
    best_provider = ""
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                try:
                    prov, text = d.result()
                except Exception:
                    continue
                if text:
                    best_provider = prov
                    best_text = text
                    for p in pending:
                        p.cancel()
                    pending.clear()
                    break
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    if best_text:
        set_fast_cache(cache_key, best_text)
        log_fn("server", "weather.provider_win", provider=best_provider, city=city_raw, day_offset=day_offset)
        return best_text

    tc = await asyncio.to_thread(fetch_weather_tool_call_quick, city)
    if isinstance(tc, dict):
        concise = agentic_loop._format_weather_from_wttr_result(tc, city_raw, day_offset)
        if concise:
            set_fast_cache(cache_key, concise)
            log_fn("server", "weather.provider_win", provider="wttr_fallback", city=city_raw, day_offset=day_offset)
            return concise

    return f"我这次没拿到{city_raw}的天气数据。你可以稍后再试。"


async def undo_fastpath(tool_executor: Any) -> str:
    try:
        res = await tool_executor.execute("fs_undo_last", {})
        if res.success:
            return "哼…我已经把上一步撤销了。要我再撤一次也行。"
        return f"撤销失败：{res.error_message}"
    except Exception as exc:
        return f"撤销失败：{exc}"

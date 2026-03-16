from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core.interaction_state import (
    PendingChatFollowup,
    PendingConfirmInferredCommand,
    PendingConfirmTool,
    PendingVideoFollowup,
)
from core.realtime_handlers import (
    extract_video_followup_correction_text,
    extract_video_subject,
    is_open_only_followup_text,
    normalize_video_query_for_search,
    video_subject_match_score,
)
from core.realtime_lane import is_cancel_text, is_confirm_text, resolve_pending_inferred_command


@dataclass(frozen=True)
class PendingHandlerResult:
    handled: bool
    clear_pending: bool = False
    speech: str = ""
    log_path: str = ""
    new_user_input: str = ""
    new_route_hint: str = ""
    set_pending: Any = None
    run_agent_loop: bool = False
    record_turn: bool = False
    preserve_pending: bool = False


async def handle_pending_video_followup(
    pending: Any,
    *,
    user_input: str,
    current_emotion: str,
    tool_executor: Any,
    make_pending_followup: Callable[..., Any],
) -> PendingHandlerResult:
    text = str(user_input or "").strip()
    last_url = str(getattr(pending, "last_url", "") or "").strip()
    last_title = str(getattr(pending, "last_title", "") or "").strip()

    if is_open_only_followup_text(text) and last_url:
        open_res = await tool_executor.execute("open_url", {"url": last_url})
        if open_res.success:
            speech = f"好，已经为你打开：{last_title}。" if last_title else "好，已经为你打开。"
        else:
            speech = "我没能成功打开链接，你可以再说一次‘打开’。"
        return PendingHandlerResult(
            handled=True,
            clear_pending=False,
            speech=speech,
            log_path="video_followup_open_last",
        )

    corrected = extract_video_followup_correction_text(text)
    if is_cancel_text(text):
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech="好，那我先不继续找。",
            log_path="video_followup_cancel",
        )

    if corrected:
        q2 = normalize_video_query_for_search(corrected) or corrected
        low2 = q2.lower()
        if not (("视频" in q2) or any(k in low2 for k in ("youtube", "youtuber", "video", "bilibili")) or any(k in q2 for k in ("b站", "哔哩", "哔哩哔哩"))):
            q2 = f"{q2} 最新视频"
        src2 = str(getattr(pending, "source", "youtube") or "youtube")
        sort2 = str(getattr(pending, "sort", "latest") or "latest")
        res2 = await tool_executor.execute(
            "search",
            {"query": q2, "source": src2, "sort": sort2, "max_results": 5},
        )
        try:
            payload2 = json.loads(str(res2.result or "{}"))
        except Exception:
            payload2 = {}
        items2 = payload2.get("items") if isinstance(payload2, dict) else None
        if isinstance(items2, list) and items2:
            top2 = items2[0] if isinstance(items2[0], dict) else {}
            subject2 = extract_video_subject(q2)
            if subject2:
                best2_score = -1.0
                best2_item = top2
                for it2 in items2:
                    if not isinstance(it2, dict):
                        continue
                    sc2 = video_subject_match_score(subject2, it2)
                    if sc2 > best2_score:
                        best2_score = sc2
                        best2_item = it2
                if best2_score >= 2.0:
                    top2 = best2_item
            title2 = str(top2.get("title") or "").strip()
            url2 = str(top2.get("url") or "").strip()
            channel2 = str(top2.get("snippet") or "").strip()
            channel_hint2 = f"（频道：{channel2}）" if channel2 and len(channel2) <= 40 else ""
            if title2 and url2:
                return PendingHandlerResult(
                    handled=True,
                    clear_pending=False,
                    speech=f"我找到一个最新视频候选：{title2}{channel_hint2}。如果不是这个，你可以继续纠正我。",
                    log_path="video_followup_retry",
                    set_pending=make_pending_followup(
                        source=src2,
                        sort=sort2,
                        last_url=url2,
                        last_title=title2,
                        last_channel=channel2,
                    ),
                )
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech="我这次还是没命中。你可以给我更完整的博主名或平台。",
            log_path="video_followup_retry_miss",
        )

    return PendingHandlerResult(handled=False, clear_pending=True)


async def handle_pending_inferred_command(
    pending: Any,
    *,
    user_input: str,
    current_emotion: str,
    tool_executor: Any,
    agentic_loop: Any,
    classify_route: Callable[[str], str],
) -> PendingHandlerResult:
    text = str(user_input or "").strip()
    resolution = resolve_pending_inferred_command(
        str(getattr(pending, "name", "") or ""),
        getattr(pending, "arguments", {}) if isinstance(getattr(pending, "arguments", {}), dict) else {},
        text,
    )
    if resolution.action == "execute":
        name = str(getattr(pending, "name", "") or "").strip()
        args_confirm = dict(getattr(pending, "arguments", {}) or {})
        result = await tool_executor.execute(name, args_confirm)
        tc = {
            "name": name,
            "arguments": args_confirm,
            "success": result.success,
            "result": result.result,
            "error_type": getattr(result, "error_type", None),
            "error_message": getattr(result, "error_message", None),
        }
        reply = agentic_loop._command_reply_from_tools([tc]) or agentic_loop._fallback_text_from_tools([tc], text) or "已执行。"
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech=reply,
            log_path="confirm_inferred_execute",
        )
    if resolution.action == "cancel":
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech="好，我先不执行。你可以直接说要我怎么做。",
            log_path="confirm_inferred_cancel",
        )
    route_hint = ""
    if resolution.corrected_text:
        route_hint = classify_route(resolution.corrected_text)
    return PendingHandlerResult(
        handled=False,
        clear_pending=True,
        new_user_input=resolution.corrected_text or text,
        new_route_hint=route_hint,
        run_agent_loop=True,
    )


async def handle_pending_confirm_tool(
    pending: Any,
    *,
    user_input: str,
    current_emotion: str,
    tool_executor: Any,
    is_undo_request: Callable[[str], bool],
) -> PendingHandlerResult:
    tool_name = str(getattr(pending, "name", "") or "").strip()
    tool_args = getattr(pending, "arguments", {}) or {}
    text = str(user_input or "").strip()

    if is_cancel_text(text) or is_undo_request(text):
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech="好，我不删。",
            log_path="pending_confirm_cancel",
        )

    if is_confirm_text(text):
        async def _always_yes(_name, _args):
            return True

        args = dict(tool_args) if isinstance(tool_args, dict) else {}
        args["confirmed"] = True
        result = await tool_executor.execute(tool_name, args, require_confirmation=_always_yes)
        if result.success:
            speech = "嗯，已经处理好了。需要撤销就说‘撤销上一步’。"
        else:
            speech = f"没成功：{result.error_message}"
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech=speech,
            log_path="pending_confirm_execute",
        )

    return PendingHandlerResult(handled=False, clear_pending=False, preserve_pending=True)


async def handle_pending_chat_followup(
    pending: Any,
    *,
    user_input: str,
    current_emotion: str,
    infer_chat_topic: Callable[[str], str],
    structured_chat_followup: Callable[[str, str], str | None],
    polish_chat_response: Callable[[str], str],
    think_action: Callable[[str, list, list, str, str], list],
    history_provider: Callable[[], list],
) -> PendingHandlerResult:
    asked = str(getattr(pending, "asked", "") or "").strip()
    topic = str(getattr(pending, "topic", "") or "").strip()
    inferred = infer_chat_topic(user_input)

    if inferred and topic and inferred != topic:
        return PendingHandlerResult(handled=False, clear_pending=True)

    structured = None
    try:
        structured = structured_chat_followup(topic, user_input)
    except Exception:
        structured = None

    if structured:
        return PendingHandlerResult(
            handled=True,
            clear_pending=True,
            speech=polish_chat_response(str(structured)),
            log_path="pending_chat_structured",
        )

    try:
        history = history_provider()
    except Exception:
        history = []

    followup_input = str(user_input or "")
    if asked:
        followup_input = f"上一轮你问：{asked}\n用户补充：{user_input}\n请给出具体建议。"
    response_stream = await asyncio.to_thread(
        think_action,
        followup_input,
        [],
        history,
        current_emotion,
        "chat",
    )
    full_response = ""
    for chunk in response_stream:
        full_response += getattr(chunk, "text", str(chunk))
    return PendingHandlerResult(
        handled=True,
        clear_pending=True,
        speech=polish_chat_response(full_response),
        log_path="pending_chat_model",
        record_turn=True,
    )


async def handle_pending_action(
    pending: Any,
    *,
    user_input: str,
    current_emotion: str,
    tool_executor: Any,
    make_pending_followup: Callable[..., Any],
    agentic_loop: Any,
    classify_route: Callable[[str], str],
    is_undo_request: Callable[[str], bool],
    infer_chat_topic: Callable[[str], str],
    structured_chat_followup: Callable[[str, str], str | None],
    polish_chat_response: Callable[[str], str],
    think_action: Callable[[str, list, list, str, str], list],
    history_provider: Callable[[], list],
) -> PendingHandlerResult:
    if isinstance(pending, PendingVideoFollowup):
        return await handle_pending_video_followup(
            pending,
            user_input=user_input,
            current_emotion=current_emotion,
            tool_executor=tool_executor,
            make_pending_followup=make_pending_followup,
        )
    if isinstance(pending, PendingConfirmInferredCommand):
        return await handle_pending_inferred_command(
            pending,
            user_input=user_input,
            current_emotion=current_emotion,
            tool_executor=tool_executor,
            agentic_loop=agentic_loop,
            classify_route=classify_route,
        )
    if isinstance(pending, PendingConfirmTool):
        return await handle_pending_confirm_tool(
            pending,
            user_input=user_input,
            current_emotion=current_emotion,
            tool_executor=tool_executor,
            is_undo_request=is_undo_request,
        )
    if isinstance(pending, PendingChatFollowup):
        result = await handle_pending_chat_followup(
            pending,
            user_input=user_input,
            current_emotion=current_emotion,
            infer_chat_topic=infer_chat_topic,
            structured_chat_followup=structured_chat_followup,
            polish_chat_response=polish_chat_response,
            think_action=think_action,
            history_provider=history_provider,
        )
        if result.handled and result.speech:
            return PendingHandlerResult(
                handled=True,
                clear_pending=result.clear_pending,
                speech=result.speech,
                log_path=result.log_path,
                record_turn=True,
            )
        return result
    return PendingHandlerResult(handled=False, clear_pending=False)

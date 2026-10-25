"""D7: run the desktop fast path the intent router chose (one table instead of a chain of if-blocks).

Each handler takes the routed request and returns (reply, log path), or None to let the general local-model loop
handle it (e.g. no recent failure to attach a "我是这样做的" to, or a site OpenCLI does not cover).
"""
from __future__ import annotations

import sys
from typing import Callable

# Chat needs no tools, memory dump or tool instructions: the full agent prompt was 2,200–3,600 tokens, i.e.
# 7–11 s of prompt reading for a 10-token answer on the 4B model (10-26). A short, fixed system prompt first
# (reused from the server's prompt cache between turns) plus the last few turns.
CHAT_SYSTEM = ('你是 Kage，用户电脑上的桌面助手，性格友好、说话简洁。直接回答用户的问题或陪他聊天；'
               '不知道就说不知道，不要编造。回答尽量控制在三句话以内，除非用户要详细解释。')
CHAT_HISTORY_TURNS = 6


def chat_messages(text: str, history: list[dict]) -> list[dict]:
    recent = [m for m in history if m.get('role') in ('user', 'assistant')][-CHAT_HISTORY_TURNS:]
    return ([{'role': 'system', 'content': CHAT_SYSTEM}]
            + [{'role': m['role'], 'content': str(m['content'])[:400]} for m in recent]
            + [{'role': 'user', 'content': text}])


MAC_ONLY = {'calendar', 'mail_list', 'mail_pick', 'wechat_unread', 'wechat_send', 'open_app'}
DESKTOP_INTENTS = MAC_ONLY | {'website', 'usage_log', 'user_method'}


def handle(route: dict, text: str, *, model, activity_log=None,
           on_method: Callable[[dict], None] | None = None) -> tuple[str, str] | None:
    intent = route['intent']
    if intent not in DESKTOP_INTENTS or (intent in MAC_ONLY and sys.platform != 'darwin'):
        return None
    if intent == 'calendar':
        from core.calendar_brief import reply_for
        return reply_for(route.get('day', 'today')), 'calendar_fastpath'
    if intent == 'mail_list':
        from core.mail_reader import list_reply
        return list_reply(), 'mail_fastpath'
    if intent == 'mail_pick':
        from core.mail_reader import message_number, pick_reply

        def summarize(prompt: str) -> str:            # mail content stays on this Mac: local model only
            response = model.generate(messages=[{'role': 'user', 'content': prompt}], max_tokens=300, temperature=0.3)
            return str(getattr(response, 'text', '') or '').strip() or '（没能生成总结）'
        return pick_reply(message_number(text), route.get('mail_mode', 'read'), summarize), 'mail_fastpath'
    if intent == 'wechat_unread':
        from core.wechat_reader import unread_reply
        return unread_reply(), 'wechat_fastpath'
    if intent == 'wechat_send':
        from core.wechat_sender import answer_routed
        return answer_routed(text, model), 'wechat_send'
    if intent == 'open_app':
        from core.tools.app_index import open_app_reply
        return open_app_reply(text, routed=True), 'open_app_fastpath'
    if intent == 'website':
        from core.tools.opencli_tool import LAST_DECISION, answer_with_site
        reply = answer_with_site(model, text)
        if not reply:
            return None
        return reply, 'opencli_clef' if str(LAST_DECISION.get('by', '')).startswith('clef') else 'opencli_site'
    if intent == 'usage_log' and activity_log is not None:
        return activity_log.summary(), 'activity_log'
    if intent == 'user_method' and activity_log is not None:
        attached = activity_log.attach_user_method(text, routed=True)
        if attached is None:
            return None
        if on_method:
            on_method(attached)
        return f"记下了：下次遇到“{attached['request'][:30]}”这类事，我照你的做法来。", 'desktop_lesson'
    return None

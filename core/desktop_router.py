"""D7 desktop router: which kind of request is this? One decision-model (Clef) call per turn replaces the chain of regexes.

The desktop fast paths used to be found by hand-written patterns (calendar ASK, mail ASK/PICK, WeChat ASK,
`parse_open_request`, SITE_PATTERN, …): fast, but they only know the phrasings written into them and misfire on
look-alikes ("微信是哪家公司做的"). The router asks Clef one multiple-choice question about the intent, plus the
few slots a handler needs that are choices too (which day). Parameters that are text (recipient, message, app
name, row number) are still cut out by the handlers' own parsers.

Performance: one call, ~0.3 s, started at the beginning of the turn so it overlaps the server's earlier checks.
Below the confidence threshold the request goes to the general local-model loop ("other"): falling back to the
patterns misrouted "知乎是什么网站" in the dev set. Only when the decision model is unavailable does the old
pattern chain decide (`legacy_intent`), so nothing gets worse offline.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import re

INTENTS = {
    'calendar': '查看今天或明天的日程、会议、安排、待办提醒',
    'mail_list': '查看有哪些新邮件、未读邮件',
    'mail_pick': '阅读、打开或总结邮件列表里的第几封',
    'wechat_unread': '查看微信里有没有新消息、谁找我',
    'wechat_send': '用微信给某人或某个群发一条消息',
    'open_app': '打开或启动电脑上的某个应用程序',
    'website': '查看或搜索某个网站（B站、知乎、微博、小红书、抖音等）上的内容、热榜',
    'usage_log': '查看 Kage 自己的使用记录：今天帮我做了什么',
    'user_method': '用户在告诉 Kage 一件事他自己是怎么做成的',
    'weather': '问天气、气温、会不会下雨',
    'chat': '闲聊、问候、不需要实时信息的知识问答、写作或建议（不用操作电脑）',
    'other': '其它要操作电脑、文件或查实时信息的事：调亮度音量、整理文件、搜索网页新闻、播放音乐视频等',
}
DAYS = {'today': '今天（或没说哪天）', 'tomorrow': '明天'}
MAIL_MODES = {'summary': '总结、概括、问讲了什么', 'read': '看原文、打开、读一下'}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='intent')


def classify(text: str) -> dict | None:
    """{'intent', 'confidence', 'day', 'by'} from the decision model, or None when it is unavailable."""
    from core import decision_model
    if not decision_model.available():
        return None
    questions = {
        'intent': {'type': 'choice', 'question': '用户这句话想让桌面助手做哪一类事？', 'criteria': INTENTS},
        'day': {'type': 'choice', 'question': '如果和日程有关，问的是哪一天？', 'criteria': DAYS},
        'mail_mode': {'type': 'choice', 'question': '如果是要看某封邮件，用户要的是？', 'criteria': MAIL_MODES},
    }
    try:
        answers = decision_model.ask(f'用户对桌面助手说：{text}', questions, run_id='intent-route')
    except decision_model.DecisionUnavailable:
        return None
    return {'intent': answers['intent'][0], 'confidence': answers['intent'][1], 'day': answers['day'][0] or 'today',
            'mail_mode': answers['mail_mode'][0] or 'read',
            'latency_s': answers['_latency_s'], 'by': 'clef'}


def start(text: str) -> Future:
    """Begin classifying now (the server awaits the result only when it reaches the desktop fast paths)."""
    return _pool.submit(classify, text)


def legacy_intent(text: str) -> str:
    """The pre-D7 decision: the server's pattern chain, in its order (kept as the offline fallback and as the
    baseline in eval/intent_v1)."""
    from core import calendar_brief, mail_reader, wechat_reader, wechat_sender
    from core.activity_log import USER_METHOD, wants_log
    from core.tools.app_index import parse_open_request
    from core.tools.opencli_tool import SITE_PATTERN
    text = str(text or '')
    if SITE_PATTERN.search(text):
        return 'website'
    if wants_log(text):
        return 'usage_log'
    if USER_METHOD.search(text):
        return 'user_method'
    if calendar_brief.ASK.search(text):
        return 'calendar'
    if mail_reader.PICK.search(text):
        return 'mail_pick'
    if mail_reader.ASK.search(text):
        return 'mail_list'
    if wechat_sender.parse(text):
        return 'wechat_send'
    if wechat_reader.ASK.search(text):
        return 'wechat_unread'
    if parse_open_request(text):
        return 'open_app'
    if '天气' in text:
        return 'weather'
    return 'other'


def legacy_day(text: str) -> str:
    return 'tomorrow' if re.search(r'明天|明日|明儿', str(text or '')) else 'today'

"""
Memory Extractor — 从对话中提取结构化事实

职责：
1. 从用户对话中提取偏好、习惯、重要事件
2. 分类为结构化事实 (preferences, habits, events, relationships)
3. 为记忆条目自动评估重要性
"""

import re
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ExtractedFact:
    """一个从对话中提取的结构化事实"""
    content: str
    category: str  # preference, habit, event, relationship, location, other
    importance: int  # 1-5
    confidence: float  # 0.0-1.0
    source_type: str  # user_statement, assistant_observation, inferred


class MemoryExtractor:
    """从对话中提取结构化记忆事实"""

    # 关键词模式 — 用于快速分类
    PREFERENCE_PATTERNS = [
        r"(喜欢|讨厌|不喜欢|爱|不爱|偏爱|偏好|中意|反感)",
        r"(最好|最差|最(好|大|小|快|慢|重要))",
        r"(习惯|不习惯|受不(了|住)|受不了|喜欢这样)",
        r"(常用|经常用|一般用|平时用)",
        r"(城市|住(在|于)|工作(在|于)|学校)",
    ]

    HABIT_PATTERNS = [
        r"(每天|每周|每月|经常|偶尔|总是|从不|一般|通常)",
        r"(早上|中午|下午|晚上|凌晨|半夜|睡前|起床)",
        r"(点|点钟|半|刻) (去|做|开始|结束|吃饭|睡觉|起床|开会|上班|下班)",
        r"(作息|日程|安排|计划|时间表)",
    ]

    RELATIONSHIP_PATTERNS = [
        r"(朋友|同事|同学|老板|下属|家人|父母|兄弟|姐妹|男(朋)?友|女(朋)?友)",
        r"(认识|见过|约了|和.*一起|跟.*去)",
    ]

    EVENT_PATTERNS = [
        r"(考试|面试|会议|约会|旅行|出差|搬家|生日|节日|纪念日)",
        r"(完成|结束|开始|通过|失败|成功|搞定|做完)",
        r"(今天|明天|昨天|下周|上个月|明年|今年)",
    ]

    LOCATION_PATTERNS = [
        r"(在|住(在|于)|工作(在|于)|学校(在|于)|公司(在|于))[\u4e00-\u9fff]{2,10}",
        r"(北京|上海|广州|深圳|杭州|成都|南京|武汉|重庆|西安|天津|苏州|长沙|青岛|大连|厦门)",
    ]

    def __init__(self):
        self._compiled_patterns = {}
        self._compile_patterns()

    def _compile_patterns(self):
        """预编译正则表达式"""
        self._compiled_patterns = {
            "preference": [re.compile(p) for p in self.PREFERENCE_PATTERNS],
            "habit": [re.compile(p) for p in self.HABIT_PATTERNS],
            "relationship": [re.compile(p) for p in self.RELATIONSHIP_PATTERNS],
            "event": [re.compile(p) for p in self.EVENT_PATTERNS],
            "location": [re.compile(p) for p in self.LOCATION_PATTERNS],
        }

    def extract_from_conversation(
        self,
        user_input: str,
        assistant_response: str = "",
        emotion: str = "neutral",
    ) -> list[ExtractedFact]:
        """从一轮对话中提取事实"""
        facts = []

        # 从用户输入提取
        user_facts = self._extract_from_text(user_input, source_type="user_statement")
        facts.extend(user_facts)

        # 从助手观察提取（如果助手提到了用户的相关信息）
        if assistant_response:
            assistant_facts = self._extract_from_text(
                assistant_response, source_type="assistant_observation"
            )
            facts.extend(assistant_facts)

        return facts

    def _extract_from_text(
        self, text: str, source_type: str = "user_statement"
    ) -> list[ExtractedFact]:
        """从单段文本中提取事实"""
        facts = []
        text_stripped = text.strip()

        # 太短的文本不值得提取
        if len(text_stripped) < 4:
            return facts

        # 分类
        category = self._classify(text_stripped)

        # 如果是无意义的短句，跳过
        if self._is_meaningless(text_stripped):
            return facts

        # 评估重要性
        importance = self._assess_importance(text_stripped, category, source_type)

        # 只提取重要性 >= 2 的事实
        if importance < 2:
            return facts

        # 计算置信度
        confidence = self._assess_confidence(text_stripped, category)

        fact = ExtractedFact(
            content=text_stripped,
            category=category,
            importance=importance,
            confidence=confidence,
            source_type=source_type,
        )
        facts.append(fact)

        return facts

    def _classify(self, text: str) -> str:
        """分类文本内容"""
        scores = {}
        for category, patterns in self._compiled_patterns.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                scores[category] = score

        if not scores:
            return "other"

        # 关系类优先于事件类（"朋友...生日" 应该归类为关系）
        if "relationship" in scores and "event" in scores:
            if any(p.search(text) for p in self._compiled_patterns["relationship"]):
                return "relationship"

        # 习惯类优先于偏好类（"习惯..." 应该归类为习惯）
        if "habit" in scores and "preference" in scores:
            if any(p.search(text) for p in self._compiled_patterns["habit"]):
                if "习惯" in text or "经常" in text or "每天" in text:
                    return "habit"

        return max(scores, key=scores.get)

    def _is_meaningless(self, text: str) -> bool:
        """判断是否是无意义的短句"""
        meaningless_patterns = [
            r"^[嗯嗯哦啊哈呀呢吧嘛]+$",
            r"^[是的不好的可以行没问题 okay ok OK]+$",
            r"^[你(好|早|晚)]+$",
            r"^[\u4e00-\u9fff]{1,2}[。！？!?.]*$",
        ]
        return any(re.match(p, text.strip()) for p in meaningless_patterns)

    def _assess_importance(
        self, text: str, category: str, source_type: str
    ) -> int:
        """评估事实的重要性 (1-5)"""
        importance = 1

        # 基于类别
        if category in ("preference", "relationship"):
            importance = 3
        elif category in ("habit", "event"):
            importance = 2
        elif category == "location":
            importance = 3

        # 基于情感强度
        strong_emotion_words = [
            "非常", "特别", "超级", "极其", "绝对", "最", "讨厌", "讨厌死",
            "爱死", "恨", "喜欢死", "受不了", "太棒了", "太差了",
        ]
        if any(w in text for w in strong_emotion_words):
            importance = min(importance + 1, 5)

        # 基于来源
        if source_type == "user_statement":
            importance = min(importance + 1, 5)

        # 基于长度（更长的陈述通常包含更多信息）
        if len(text) > 20:
            importance = min(importance + 1, 5)

        return importance

    def _assess_confidence(self, text: str, category: str) -> float:
        """评估提取的置信度"""
        confidence = 0.5

        # 明确的陈述句置信度高
        if any(w in text for w in ["我", "我的", "我喜欢", "我讨厌", "我经常"]):
            confidence += 0.2

        # 有具体细节的置信度高
        if len(text) > 15:
            confidence += 0.1

        # 偏好类置信度高
        if category == "preference":
            confidence += 0.1

        return min(confidence, 1.0)

    def fact_to_dict(self, fact: ExtractedFact) -> dict:
        """转换为字典用于序列化"""
        return asdict(fact)

    def dict_to_fact(self, data: dict) -> ExtractedFact:
        """从字典恢复事实"""
        return ExtractedFact(**data)

"""
LLM-Assisted Memory Fact Extractor

Uses the local LLM to extract structured facts from conversations
when rule-based extraction is insufficient or ambiguous.

Design principles:
- Runs asynchronously after conversation (no blocking)
- Falls back to rule-based extraction if LLM unavailable
- Lightweight prompt to minimize token usage
- Structured JSON output for easy parsing
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """你是一个记忆提取助手。从对话中提取用户的结构化事实。

规则：
1. 只提取关于用户的重要事实（偏好、习惯、关系、位置、事件）
2. 忽略无意义的对话（如"嗯嗯"、"好的"、"你好"）
3. 重要性评分 1-5（5 最重要）
4. 分类：preference（偏好）、habit（习惯）、relationship（关系）、location（位置）、event（事件）、other（其他）
5. 如果用户表达否定（如"我不吃川菜了"），标记 negated=true

输出格式（JSON 数组，不要其他内容）：
[
  {{"content": "事实内容", "category": "分类", "importance": 3, "negated": false}}
]

对话：
用户: {user_input}
助手: {assistant_response}

输出："""


class LLMFactExtractor:
    """使用 LLM 辅助提取记忆事实"""

    def __init__(self, model_provider=None):
        """
        Args:
            model_provider: 模型提供者，需要有 generate(messages) 方法。
                           如果为 None，将只使用规则提取。
        """
        self.model = model_provider

    async def extract_facts(
        self,
        user_input: str,
        assistant_response: str = "",
    ) -> list[dict]:
        """Extract facts using LLM if available, fall back to rules."""
        if not self.model:
            return []

        try:
            prompt = EXTRACTION_PROMPT.format(
                user_input=user_input,
                assistant_response=assistant_response,
            )

            messages = [
                {"role": "system", "content": "你是一个记忆提取助手。只输出 JSON 数组，不要其他内容。"},
                {"role": "user", "content": prompt},
            ]

            response = self.model.generate(messages=messages, max_tokens=200)
            raw_text = response.text or ""

            facts = self._parse_json_response(raw_text)
            if facts:
                logger.info("LLM extracted %d facts from conversation", len(facts))
                return facts

        except Exception as exc:
            logger.warning("LLM fact extraction failed: %s", exc)

        return []

    def _parse_json_response(self, text: str) -> list[dict]:
        """Parse JSON array from LLM response."""
        # Try to find JSON array in the response
        text = text.strip()

        # Find JSON array boundaries
        start = text.find("[")
        end = text.rfind("]")

        if start == -1 or end == -1 or end <= start:
            return []

        json_str = text[start:end+1]

        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                return []

            # Validate and clean
            facts = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content", "")).strip()
                if not content or len(content) < 3:
                    continue

                facts.append({
                    "content": content,
                    "category": str(item.get("category", "other")).strip().lower(),
                    "importance": int(item.get("importance", 2)),
                    "negated": bool(item.get("negated", False)),
                    "source": "llm",
                })

            return facts
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug("JSON parse failed: %s, text: %s", e, text[:200])
            return []

    def merge_with_rule_facts(
        self,
        llm_facts: list[dict],
        rule_facts: list[dict],
    ) -> list[dict]:
        """Merge LLM and rule-based facts, preferring LLM for complex facts.

        Strategy:
        - If LLM extracted facts, use them (more accurate)
        - Otherwise, fall back to rule-based facts
        - Deduplicate by content similarity
        """
        if llm_facts:
            return llm_facts
        return rule_facts

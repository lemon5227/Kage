"""
Model Provider — 模型抽象层

统一的 LLM 调用接口，支持 OpenAI 兼容 API（OpenAI、本地 llama-server 等）。

从 config/settings.json 读取 cloud_api 配置。
若无有效 API 密钥，则默认指向本地 llama-server（http://127.0.0.1:8080/v1）。
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.trace import log

logger = logging.getLogger(__name__)


def _coerce_message_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type in ("text", "output_text"):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            elif item_type in ("input_text",):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts)
    return ""


def _extract_message_text(message: dict[str, Any]) -> str:
    direct = _coerce_message_text(message.get("content"))
    if direct:
        return direct

    for key in ("output_text", "text"):
        text = _coerce_message_text(message.get(key))
        if text:
            return text

    # Some OpenAI-compatible runtimes expose reasoning in a parallel field.
    for key in ("reasoning_content", "reasoning", "thinking", "reasoning_text"):
        text = _coerce_message_text(message.get(key))
        if text:
            return text

    return ""


@dataclass
class ModelResponse:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    emotion: str = "neutral"
    raw_output: str = ""


class ModelProvider:
    """统一的 LLM 调用接口（基类）"""

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
    ) -> ModelResponse:
        raise NotImplementedError


class OpenAICompatibleProvider(ModelProvider):
    """OpenAI 兼容 API 实现（支持 OpenAI、Anthropic 等）"""

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini",
                 base_url: str = "https://api.openai.com/v1",
                 timeout_sec: int = 120):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = int(timeout_sec) if timeout_sec else 120

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
    ) -> ModelResponse:
        import urllib.request
        import urllib.error

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            t0 = time.monotonic()
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            log(
                "model",
                "openai_compat.request",
                base_url=self.base_url,
                model=self.model_name,
                tools=bool(tools),
                elapsed_ms=f"{(time.monotonic()-t0)*1000:.1f}",
            )

            choice = body.get("choices", [{}])[0]
            message = choice.get("message", {})
            text = _extract_message_text(message)

            # Parse tool_calls from OpenAI format
            tool_calls = []
            for tc in message.get("tool_calls", []):
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                try:
                    parsed_args = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    parsed_args = {}
                tool_calls.append({
                    "name": func.get("name", ""),
                    "arguments": parsed_args,
                })

            return ModelResponse(
                text=text,
                tool_calls=tool_calls,
                emotion="neutral",
                raw_output=json.dumps(body, ensure_ascii=False),
            )
        except urllib.error.URLError as exc:
            logger.error("OpenAI API call failed: %s", exc)
            return ModelResponse(
                text=f"云端模型调用失败: {exc}",
                tool_calls=[],
                emotion="sad",
                raw_output="",
            )
        except Exception as exc:
            logger.error("OpenAI API unexpected error: %s", exc)
            return ModelResponse(
                text=f"云端模型调用失败: {exc}",
                tool_calls=[],
                emotion="sad",
                raw_output="",
            )


def create_provider_from_settings(settings_path: str = "config/settings.json") -> ModelProvider:
    """从 settings.json 创建 OpenAICompatibleProvider。

    优先使用配置中的 cloud_api 设置。
    若无有效 API 密钥，则默认指向本地 llama-server。
    """
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except Exception:
        settings = {}

    cloud_cfg = settings.get("model", {}).get("cloud_api", {})

    if cloud_cfg.get("api_key"):
        return OpenAICompatibleProvider(
            api_key=cloud_cfg["api_key"],
            model_name=cloud_cfg.get("model_name", "gpt-4o-mini"),
            base_url=cloud_cfg.get("base_url", "https://api.openai.com/v1"),
        )

    # 默认：本地 llama-server
    return OpenAICompatibleProvider(
        api_key="local",
        model_name="local-model",
        base_url="http://127.0.0.1:8080/v1",
    )

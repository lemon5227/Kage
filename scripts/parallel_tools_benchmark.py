#!/usr/bin/env python3
"""Micro benchmark for parallel read-only tool execution in AgenticLoop.

Compares:
- parallel candidate batch (two read-only tools)
- forced serial batch (one read-only + one side-effect tool)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import sys


ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.agentic_loop import AgenticLoop
from core.model_provider import ModelResponse


class _DummyPrompt:
    def __init__(self, tools):
        self._tools = tools
        self.last_route = "info"

    def build(self, user_input, history, current_emotion="neutral"):
        self.last_route = "info"
        return [
            {"role": "system", "content": "s"},
            {"role": "user", "content": str(user_input or "")},
        ], self._tools


class _DummySession:
    def get_history(self):
        return []


class _DummyModel:
    def __init__(self, tool_calls):
        self._tool_calls = tool_calls
        self._called = False

    def generate(self, messages, tools=None, max_tokens=200, temperature=0.7):
        if not self._called:
            self._called = True
            return ModelResponse(text="", tool_calls=self._tool_calls)
        return ModelResponse(text="done", tool_calls=[])


class _ToolResult:
    def __init__(self, name, success, result, elapsed_ms=0.0):
        self.name = name
        self.success = success
        self.result = result
        self.error_type = None
        self.error_message = None
        self.elapsed_ms = elapsed_ms


class _DummyExecutor:
    def __init__(self, sleep_sec=0.25):
        self.sleep_sec = float(sleep_sec)
        self.active = 0
        self.max_active = 0

    def parse_tool_calls(self, text):
        return []

    async def execute(self, name, arguments):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        t0 = time.monotonic()
        try:
            await asyncio.sleep(self.sleep_sec)
            if name == "web_fetch":
                payload = json.dumps({"success": True, "content": "hello world"}, ensure_ascii=False)
                return _ToolResult(name, True, payload, elapsed_ms=(time.monotonic() - t0) * 1000)
            return _ToolResult(name, True, "ok", elapsed_ms=(time.monotonic() - t0) * 1000)
        finally:
            self.active -= 1


def _run_case(tool_calls):
    tool_defs = [
        {"type": "function", "function": {"name": "web_fetch", "description": "", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "open_app", "description": "", "parameters": {"type": "object"}}},
    ]
    ex = _DummyExecutor(sleep_sec=0.25)
    loop = AgenticLoop(
        model_provider=_DummyModel(tool_calls=tool_calls),
        tool_executor=ex,
        prompt_builder=_DummyPrompt(tool_defs),
        session_manager=_DummySession(),
    )
    t0 = time.monotonic()
    res = asyncio.run(loop.run("测试并行工具"))
    wall_ms = (time.monotonic() - t0) * 1000
    return {
        "wall_ms": round(wall_ms, 1),
        "max_active": ex.max_active,
        "steps": res.steps,
        "final_text": str(res.final_text or "")[:120],
    }


def main() -> int:
    parallel = _run_case(
        [
            {"name": "web_fetch", "arguments": {"url": "https://a.example.com"}},
            {"name": "web_fetch", "arguments": {"url": "https://b.example.com"}},
        ]
    )
    serial = _run_case(
        [
            {"name": "web_fetch", "arguments": {"url": "https://a.example.com"}},
            {"name": "open_app", "arguments": {"app_name": "Notes"}},
        ]
    )

    speedup = (serial["wall_ms"] / parallel["wall_ms"]) if parallel["wall_ms"] > 0 else 1.0
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parallel_case": parallel,
        "serial_case": serial,
        "speedup": round(speedup, 2),
    }

    out_path = Path("/Users/wenbo/Kage/docs/benchmarks/latest_parallel_tools_benchmark.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    print(f"saved={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

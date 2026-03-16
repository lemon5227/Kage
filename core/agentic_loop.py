"""
Agentic Loop — 多步智能循环

核心执行引擎：
1. Prompt_Builder 构建提示词
2. Model_Provider 生成回复
3. 如果包含工具调用 → Tool_Executor 执行 → 结果反馈 → 回到 2
4. 如果纯文本 → 返回最终结果
5. 最多循环 MAX_STEPS 次

特性：
- 重复检测：10 字符子串出现 3 次以上时停止
- 动态 max_tokens：文本 200、工具 300
- 情绪标签：thinking / happy / sad
- 工具失败时反馈给模型请求替代方案
- 空输入返回默认回复
"""

import asyncio
import logging
import json
import re
import hashlib
import time
import urllib.parse
from dataclasses import dataclass, field

from core.trace import Span, log

logger = logging.getLogger(__name__)

VALID_EMOTIONS = frozenset({
    "neutral", "happy", "sad", "angry", "surprised", "thinking", "shy",
})

DEFAULT_REPLY = "我在呢，有什么需要帮忙的吗？"


@dataclass
class LoopResult:
    final_text: str
    emotion: str = "neutral"
    tool_calls_executed: list[dict] = field(default_factory=list)
    steps: int = 0


def detect_repetition(text: str, substr_len: int = 10, threshold: int = 3) -> bool:
    """Return True if any 10-char substring appears >= 3 times."""
    if len(text) < substr_len:
        return False
    for i in range(len(text) - substr_len + 1):
        sub = text[i:i + substr_len]
        if text.count(sub) >= threshold:
            return True
    return False


class AgenticLoop:
    """多步工具调用循环"""

    MAX_STEPS = 5

    def __init__(self, model_provider, tool_executor, prompt_builder,
                 session_manager):
        self.model = model_provider
        self.tools = tool_executor
        self.prompt = prompt_builder
        self.session = session_manager

    async def run(self, user_input: str,
                  current_emotion: str = "neutral") -> LoopResult:
        """Execute the agentic loop."""

        # Empty input → default reply
        if not user_input or not str(user_input).strip():
            return LoopResult(
                final_text=DEFAULT_REPLY,
                emotion="neutral",
                steps=0,
            )

        base_user_input = str(user_input or "").strip()
        outer = Span("loop", "run", user_len=len(base_user_input))

        task_input = base_user_input
        history = self.session.get_history() or []
        tool_calls_executed: list[dict] = []
        emotion = "thinking"
        last_text = ""

        skills_installs = 0
        active_skill_name: str | None = None
        active_skill_guidance: str = ""
        skill_retry_used = False
        backup_skill: dict | None = None
        did_non_skill_tool = False
        primitive_retry_used = False
        autosave_done = False

        repeat_count = sum(
            1
            for h in (history or [])
            if isinstance(h, dict)
            and h.get("role") == "user"
            and str(h.get("content") or "").strip() == base_user_input.strip()
        )

        last_step = 0

        try:
            for step in range(1, self.MAX_STEPS + 1):
                last_step = step

                # 1) Build prompt
                t0 = time.monotonic()
                messages, tool_defs = self.prompt.build(
                    user_input=task_input,
                    history=history,
                    current_emotion=emotion,
                )
                route = str(getattr(self.prompt, "last_route", "chat") or "chat")
                log(
                    "loop",
                    "prompt.built",
                    step=step,
                    elapsed_ms=f"{(time.monotonic()-t0)*1000:.1f}",
                    tools=len(tool_defs or []),
                    history=len(history or []),
                    route=route,
                )

                # 2) Call model
                has_tools = bool(tool_defs)
                # Phase A (planner): for info route, keep decision output short.
                max_tokens = 128 if (has_tools and route == "info") else (300 if has_tools else 200)
                t1 = time.monotonic()
                response = self.model.generate(
                    messages=messages,
                    tools=tool_defs if has_tools else None,
                    max_tokens=max_tokens,
                )
                raw_text = response.text or ""
                log(
                    "loop",
                    "model.generate",
                    step=step,
                    elapsed_ms=f"{(time.monotonic()-t1)*1000:.1f}",
                    text_len=len(raw_text),
                    tool_calls=len(response.tool_calls or []),
                )

                # Repetition detection
                if detect_repetition(raw_text):
                    logger.warning("Repetition detected at step %d, stopping", step)
                    clean = self._remove_repetition(raw_text)
                    return LoopResult(
                        final_text=clean or last_text or DEFAULT_REPLY,
                        emotion="neutral",
                        tool_calls_executed=tool_calls_executed,
                        steps=step,
                    )

                # 3) Determine tool calls
                tool_calls = response.tool_calls or []
                if not tool_calls:
                    t2 = time.monotonic()
                    tool_calls = self.tools.parse_tool_calls(raw_text)
                    log(
                        "loop",
                        "tool_calls.parsed_from_text",
                        step=step,
                        elapsed_ms=f"{(time.monotonic()-t2)*1000:.1f}",
                        count=len(tool_calls or []),
                    )

                # Forced tool-call retry (file/system intents) to reduce model "chatting".
                if (
                    route != "info"
                    and not tool_calls
                    and step == 1
                    and self._needs_tool_action(base_user_input)
                    and has_tools
                ):
                    hint = self._primitive_tool_hint(base_user_input)
                    forced_input = (
                        "你必须调用工具来完成用户请求。只输出 1 个工具调用 JSON，不要解释。\n"
                        f"优先选择：{hint}\n"
                        "优先使用结构化工具（如 fs_search / fs_apply / open_url / smart_search），"
                        "不要使用 trash/删除类操作，除非用户明确说‘删除/移入废纸篓/清空’。\n"
                        f"用户请求: {base_user_input}"
                    )
                    forced_messages, forced_tools = self.prompt.build(
                        user_input=forced_input,
                        history=history,
                        current_emotion=emotion,
                    )
                    forced_resp = self.model.generate(
                        messages=forced_messages,
                        tools=forced_tools if forced_tools else None,
                        max_tokens=max_tokens,
                    )
                    raw_text = forced_resp.text or raw_text
                    tool_calls = forced_resp.tool_calls or self.tools.parse_tool_calls(raw_text)

                # If a skill is loaded but we still don't have tool calls, force a next-step tool call.
                if not tool_calls and active_skill_name and has_tools and step <= 2:
                    forced_input = (
                        "你已经加载了一个技能流程模板。现在必须严格遵循技能步骤继续执行。\n"
                        "只输出 1 个下一步工具调用 JSON，不要解释。\n"
                        "除非用户明确要求删除，否则不要用 trash/删除类操作。\n"
                        f"技能: {active_skill_name}\n"
                        f"技能指引(节选):\n{active_skill_guidance}\n\n"
                        f"用户原始请求: {base_user_input}"
                    )
                    forced_messages, forced_tools = self.prompt.build(
                        user_input=forced_input,
                        history=history,
                        current_emotion=emotion,
                    )
                    forced_resp = self.model.generate(
                        messages=forced_messages,
                        tools=forced_tools if forced_tools else None,
                        max_tokens=max_tokens,
                    )
                    raw_text = forced_resp.text or raw_text
                    tool_calls = forced_resp.tool_calls or self.tools.parse_tool_calls(raw_text)

                # If skill-based guidance still doesn't produce actionable tool calls,
                # fall back to primitives without involving the user.
                if (
                    not tool_calls
                    and (active_skill_name or skill_retry_used)
                    and has_tools
                    and step <= 2
                    and not primitive_retry_used
                    and not did_non_skill_tool
                ):
                    primitive_retry_used = True
                    hint = self._primitive_tool_hint(base_user_input)
                    forced_input = (
                        "技能流程无法直接落地执行。现在忽略技能，直接用原语工具完成用户请求。\n"
                        "只输出 1 个工具调用 JSON，不要解释。\n"
                        f"优先选择：{hint}\n"
                        "除非用户明确要求删除，否则不要用 trash/删除类操作。\n"
                        f"用户原始请求: {base_user_input}"
                    )
                    forced_messages, forced_tools = self.prompt.build(
                        user_input=forced_input,
                        history=history,
                        current_emotion=emotion,
                    )
                    forced_resp = self.model.generate(
                        messages=forced_messages,
                        tools=forced_tools if forced_tools else None,
                        max_tokens=max_tokens,
                    )
                    raw_text = forced_resp.text or raw_text
                    tool_calls = forced_resp.tool_calls or self.tools.parse_tool_calls(raw_text)

                # If we still can't progress after loading a skill, try one backup skill automatically.
                if (
                    not tool_calls
                    and active_skill_name
                    and backup_skill
                    and (not skill_retry_used)
                    and (not did_non_skill_tool)
                    and has_tools
                    and step <= 2
                ):
                    repo = str(backup_skill.get("repo") or "").strip()
                    skill = str(backup_skill.get("skill") or "").strip()
                    if repo and skill and skills_installs < 2:
                        skill_retry_used = True
                        skills_installs += 1

                        install_args = {
                            "repo": repo,
                            "skill": skill,
                            "global_install": True,
                            "agent": "opencode",
                        }
                        install_res = await self.tools.execute("skills_install", install_args)
                        tool_calls_executed.append({
                            "name": "skills_install",
                            "arguments": install_args,
                            "success": install_res.success,
                            "result": install_res.result,
                            "error_type": install_res.error_type,
                            "error_message": install_res.error_message,
                        })

                        read_args = {"skill_name": skill}
                        read_res = await self.tools.execute("skills_read", read_args)
                        tool_calls_executed.append({
                            "name": "skills_read",
                            "arguments": read_args,
                            "success": read_res.success,
                            "result": read_res.result,
                            "error_type": read_res.error_type,
                            "error_message": read_res.error_message,
                        })

                        if read_res.success and read_res.result:
                            sname, guidance = self._extract_skill_guidance(str(read_res.result))
                            if sname and guidance:
                                active_skill_name = sname
                                active_skill_guidance = guidance
                                history.append({
                                    "role": "assistant",
                                    "content": f"[Skill Guidance Loaded: {active_skill_name}]\n{guidance}",
                                })
                                task_input = (
                                    "已加载技能指引，请严格按步骤继续执行。\n"
                                    "只要能用工具完成就直接调用工具，不要闲聊。\n"
                                    f"用户请求: {base_user_input}"
                                )
                        continue

                # Command-route deterministic fallback: avoid extra model retries for
                # obvious system operations.
                if route == "command" and not tool_calls and step == 1:
                    inferred = self._infer_command_tool_call(base_user_input)
                    if inferred:
                        tool_calls = [inferred]
                        log("loop", "command.fallback_infer", step=step, tool=inferred.get("name"))

                # Info-route deterministic fallback: if the model still fails to
                # produce tool calls, directly run smart_search once and respond.
                if route == "info" and not tool_calls and step == 1:
                    try:
                        # Weather requests: prefer deterministic weather JSON endpoint.
                        if self._is_weather_query(base_user_input):
                            city = self._extract_weather_city(base_user_input)
                            day_offset = self._extract_weather_day_offset(base_user_input)
                            city_for_url = self._normalize_city_for_weather_api(city)
                            weather_url = f"https://wttr.in/{urllib.parse.quote(city_for_url)}?format=j1"
                            weather_args = {"url": weather_url}
                            weather_res = await self.tools.execute("web_fetch", weather_args)
                            log(
                                "loop",
                                "tool.result",
                                step=step,
                                name="web_fetch",
                                success=weather_res.success,
                                elapsed_ms=f"{float(getattr(weather_res, 'elapsed_ms', 0.0) or 0.0):.1f}",
                                error_type=getattr(weather_res, "error_type", None),
                            )
                            weather_tc = {
                                "name": "web_fetch",
                                "arguments": weather_args,
                                "success": weather_res.success,
                                "result": weather_res.result,
                                "error_type": getattr(weather_res, "error_type", None),
                                "error_message": getattr(weather_res, "error_message", None),
                            }
                            tool_calls_executed.append(weather_tc)
                            if weather_res.success:
                                history.append({
                                    "role": "assistant",
                                    "content": f"[Tool: web_fetch] {weather_res.result}",
                                })
                            resp_text = self._format_weather_from_wttr_result(weather_tc, city, day_offset)
                            if not resp_text:
                                resp_text = self._fallback_text_from_tools(tool_calls_executed, base_user_input)
                            if resp_text:
                                emotion = self._determine_emotion(tool_calls_executed)
                                return LoopResult(
                                    final_text=resp_text,
                                    emotion=emotion,
                                    tool_calls_executed=tool_calls_executed,
                                    steps=step,
                                )

                        info_args = {"query": base_user_input, "max_results": 5, "strategy": "auto"}
                        info_res = await self.tools.execute("smart_search", info_args)
                        log(
                            "loop",
                            "tool.result",
                            step=step,
                            name="smart_search",
                            success=info_res.success,
                            elapsed_ms=f"{float(getattr(info_res, 'elapsed_ms', 0.0) or 0.0):.1f}",
                            error_type=getattr(info_res, "error_type", None),
                        )
                        info_tc = {
                            "name": "smart_search",
                            "arguments": info_args,
                            "success": info_res.success,
                            "result": info_res.result,
                            "error_type": getattr(info_res, "error_type", None),
                            "error_message": getattr(info_res, "error_message", None),
                        }
                        tool_calls_executed.append(info_tc)

                        if info_res.success:
                            history.append({
                                "role": "assistant",
                                "content": f"[Tool: smart_search] {info_res.result}",
                            })
                        else:
                            history.append({
                                "role": "assistant",
                                "content": (
                                    f"[Tool Error: smart_search] {getattr(info_res, 'error_type', None)}: "
                                    f"{getattr(info_res, 'error_message', None)}."
                                ),
                            })

                        # Avoid another heavy model call for info fallback path.
                        resp_text = self._fallback_text_from_tools(tool_calls_executed, base_user_input)
                        if resp_text:
                            emotion = self._determine_emotion(tool_calls_executed)
                            return LoopResult(
                                final_text=resp_text,
                                emotion=emotion,
                                tool_calls_executed=tool_calls_executed,
                                steps=step,
                            )
                    except Exception:
                        pass

                # 3.5) If still no tool calls, return pure text
                if not tool_calls:
                    if not str(raw_text or "").strip() and tool_calls_executed:
                        fallback = self._fallback_text_from_tools(tool_calls_executed, base_user_input)
                        if fallback:
                            raw_text = fallback
                    if not str(raw_text or "").strip():
                        raw_text = "我这次没有拿到有效结果。要我立刻重试并换一个来源吗？"

                    if (
                        not autosave_done
                        and repeat_count >= 2
                        and did_non_skill_tool
                        and self._tool_available(tool_defs, "skills_save_local")
                        and not any(tc.get("name") == "skills_save_local" for tc in tool_calls_executed)
                    ):
                        autosave_done = True
                        try:
                            base = base_user_input.strip()
                            digest = hashlib.md5(base.encode("utf-8")).hexdigest()[:6]
                            last_tool = "workflow"
                            for tc in reversed(tool_calls_executed):
                                n = str(tc.get("name") or "").strip()
                                if n and n not in ("skills_find_remote", "web_fetch", "skills_install", "skills_read"):
                                    last_tool = n
                                    break
                            skill_name = f"auto-{last_tool}-{digest}"
                            desc = f"重复请求自动沉淀：{base}"
                            body = "\n".join(
                                [
                                    "## Goal",
                                    base,
                                    "",
                                    "## Steps",
                                    f"1. Use `{last_tool}` to complete the request.",
                                    "2. Review results and respond concisely.",
                                    "",
                                    "## Notes",
                                    "- Avoid destructive file operations unless explicitly requested.",
                                ]
                            )
                            save_args = {"name": skill_name, "description": desc, "body": body}
                            save_res = await self.tools.execute("skills_save_local", save_args)
                            tool_calls_executed.append({
                                "name": "skills_save_local",
                                "arguments": save_args,
                                "success": save_res.success,
                                "result": save_res.result,
                                "error_type": getattr(save_res, "error_type", None),
                                "error_message": getattr(save_res, "error_message", None),
                            })
                        except Exception:
                            pass

                    emotion = self._determine_emotion(tool_calls_executed)
                    return LoopResult(
                        final_text=raw_text,
                        emotion=emotion,
                        tool_calls_executed=tool_calls_executed,
                        steps=step,
                    )

                # 4) Execute tool calls
                last_text = raw_text
                step_tool_calls: list[dict] = []

                if self._can_parallelize_tool_calls(tool_calls):
                    names = [str((tc or {}).get("name") or "") for tc in tool_calls if isinstance(tc, dict)]
                    parallel_t0 = time.monotonic()
                    log("loop", "tool.parallel.start", step=step, count=len(names), names=",".join(names))

                    async def _exec_one(call: dict) -> dict:
                        n = str(call.get("name") or "")
                        a = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                        try:
                            r = await self.tools.execute(n, a)
                            return {
                                "name": n,
                                "arguments": a,
                                "success": bool(getattr(r, "success", False)),
                                "result": str(getattr(r, "result", "") or ""),
                                "error_type": getattr(r, "error_type", None),
                                "error_message": getattr(r, "error_message", None),
                                "elapsed_ms": float(getattr(r, "elapsed_ms", 0.0) or 0.0),
                            }
                        except Exception as exc:
                            return {
                                "name": n,
                                "arguments": a,
                                "success": False,
                                "result": "",
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                                "elapsed_ms": 0.0,
                            }

                    parallel_rows = await asyncio.gather(*[_exec_one(tc) for tc in tool_calls if isinstance(tc, dict)])
                    m = self._parallel_metrics(parallel_rows, wall_ms=(time.monotonic() - parallel_t0) * 1000)
                    log(
                        "loop",
                        "tool.parallel.end",
                        step=step,
                        count=m["count"],
                        wall_ms=f"{m['wall_ms']:.1f}",
                        sum_ms=f"{m['sum_ms']:.1f}",
                        max_ms=f"{m['max_ms']:.1f}",
                        saved_ms=f"{m['saved_ms']:.1f}",
                        speedup=f"{m['speedup']:.2f}",
                    )
                    for row in parallel_rows:
                        name = str(row.get("name") or "")
                        success = bool(row.get("success"))
                        log(
                            "loop",
                            "tool.result",
                            step=step,
                            name=name,
                            success=success,
                            elapsed_ms=f"{float(row.get('elapsed_ms') or 0.0):.1f}",
                            error_type=row.get("error_type"),
                        )
                        item = {
                            "name": name,
                            "arguments": row.get("arguments") if isinstance(row.get("arguments"), dict) else {},
                            "success": success,
                            "result": str(row.get("result") or ""),
                            "error_type": row.get("error_type"),
                            "error_message": row.get("error_message"),
                        }
                        tool_calls_executed.append(item)
                        step_tool_calls.append(item)
                        if name not in ("skills_find_remote", "web_fetch", "skills_install", "skills_read"):
                            did_non_skill_tool = True
                        if success:
                            history.append({"role": "assistant", "content": f"[Tool: {name}] {item['result']}"})
                        else:
                            history.append(
                                {
                                    "role": "assistant",
                                    "content": (
                                        f"[Tool Error: {name}] {item['error_type']}: "
                                        f"{item['error_message']}. 请尝试替代方案。"
                                    ),
                                }
                            )
                else:
                    for tc in tool_calls:
                        name = tc.get("name", "")
                        args = tc.get("arguments", {})
                        log("loop", "tool.call", step=step, name=str(name))

                        if name == "skills_install" and skills_installs >= 2:
                            tool_calls_executed.append({
                                "name": name,
                                "arguments": args,
                                "success": False,
                                "result": "已在本轮安装过技能，跳过重复安装。",
                            })
                            history.append({
                                "role": "assistant",
                                "content": "[Tool Error: skills_install] TooManyInstalls: 本轮最多自动安装 1 个技能。",
                            })
                            continue

                        # Auto-preview before fs_apply
                        if name == "fs_apply" and isinstance(args, dict) and isinstance(args.get("ops"), list):
                            try:
                                preview_res = await self.tools.execute("fs_preview", {"ops": args.get("ops")})
                                tool_calls_executed.append({
                                    "name": "fs_preview",
                                    "arguments": {"ops": args.get("ops")},
                                    "success": preview_res.success,
                                    "result": preview_res.result,
                                    "error_type": preview_res.error_type,
                                    "error_message": preview_res.error_message,
                                })
                                if preview_res.success and preview_res.result:
                                    history.append({
                                        "role": "assistant",
                                        "content": f"[Tool: fs_preview] {preview_res.result}",
                                    })
                            except Exception:
                                pass

                        result = await self.tools.execute(name, args)
                        log(
                            "loop",
                            "tool.result",
                            step=step,
                            name=str(name),
                            success=result.success,
                            elapsed_ms=f"{float(getattr(result, 'elapsed_ms', 0.0) or 0.0):.1f}",
                            error_type=getattr(result, "error_type", None),
                        )
                        tool_calls_executed.append({
                            "name": name,
                            "arguments": args,
                            "success": result.success,
                            "result": result.result,
                            "error_type": getattr(result, "error_type", None),
                            "error_message": getattr(result, "error_message", None),
                        })
                        step_tool_calls.append(tool_calls_executed[-1])

                        if name not in ("skills_find_remote", "web_fetch", "skills_install", "skills_read"):
                            did_non_skill_tool = True

                        # If we loaded a skill, extract guidance.
                        if name == "skills_read" and result.success and result.result:
                            sname, guidance = self._extract_skill_guidance(str(result.result))
                            if sname and guidance:
                                active_skill_name = sname
                                active_skill_guidance = guidance
                                history.append({
                                    "role": "assistant",
                                    "content": f"[Skill Guidance Loaded: {active_skill_name}]\n{guidance}",
                                })
                                task_input = (
                                    "已加载技能指引，请严格按步骤继续执行。\n"
                                    "只要能用工具完成就直接调用工具，不要闲聊。\n"
                                    f"用户请求: {base_user_input}"
                                )

                        # Auto-install flow: after skills_find_remote, install top skill and load guidance.
                        if name == "skills_find_remote" and result.success and skills_installs < 1:
                            try:
                                payload = json.loads(str(result.result or ""))
                            except Exception:
                                payload = None
                            items = (payload or {}).get("results") if isinstance(payload, dict) else None
                            if isinstance(items, list) and items:
                                candidates = [it for it in items if isinstance(it, dict)][:3]
                                picked = candidates[0] if candidates else {}
                                backup_skill = candidates[1] if len(candidates) > 1 else None
                                repo = str(picked.get("repo") or "").strip()
                                skill = str(picked.get("skill") or "").strip()
                                if repo and skill:
                                    skills_installs += 1
                                    install_args = {
                                        "repo": repo,
                                        "skill": skill,
                                        "global_install": True,
                                        "agent": "opencode",
                                    }
                                    install_res = await self.tools.execute("skills_install", install_args)
                                    tool_calls_executed.append({
                                        "name": "skills_install",
                                        "arguments": install_args,
                                        "success": install_res.success,
                                        "result": install_res.result,
                                        "error_type": install_res.error_type,
                                        "error_message": install_res.error_message,
                                    })

                                    read_args = {"skill_name": skill}
                                    read_res = await self.tools.execute("skills_read", read_args)
                                    tool_calls_executed.append({
                                        "name": "skills_read",
                                        "arguments": read_args,
                                        "success": read_res.success,
                                        "result": read_res.result,
                                        "error_type": read_res.error_type,
                                        "error_message": read_res.error_message,
                                    })

                                    if read_res.success and read_res.result:
                                        sname, guidance = self._extract_skill_guidance(str(read_res.result))
                                        if sname and guidance:
                                            active_skill_name = sname
                                            active_skill_guidance = guidance
                                            history.append({
                                                "role": "assistant",
                                                "content": f"[Skill Guidance Loaded: {active_skill_name}]\n{guidance}",
                                            })
                                            task_input = (
                                                "已加载技能指引，请严格按步骤继续执行。\n"
                                                "只要能用工具完成就直接调用工具，不要闲聊。\n"
                                                f"用户请求: {base_user_input}"
                                            )

                        # Append tool result to history
                        if result.success:
                            history.append({
                                "role": "assistant",
                                "content": f"[Tool: {name}] {result.result}",
                            })
                        else:
                            history.append({
                                "role": "assistant",
                                "content": (
                                    f"[Tool Error: {name}] {result.error_type}: "
                                    f"{result.error_message}. 请尝试替代方案。"
                                ),
                            })

                # Phase B (responder): for info route, generate final answer from tool outputs
                # instead of doing another full tool-decision round.
                if route == "info" and step_tool_calls:
                    names = {str((tc or {}).get("name") or "") for tc in step_tool_calls if isinstance(tc, dict)}
                    # Use deterministic template first for fetch/search primitives;
                    # keep two-phase model responder for smart_search planner flow.
                    prefer_template = bool(names.intersection({"web_fetch", "search"}))
                    if prefer_template:
                        resp_text = self._fallback_text_from_tools(step_tool_calls, base_user_input)
                        if not resp_text:
                            resp_text = self._respond_from_tools_with_model(base_user_input, step_tool_calls)
                    else:
                        resp_text = self._respond_from_tools_with_model(base_user_input, step_tool_calls)
                        if not resp_text:
                            resp_text = self._fallback_text_from_tools(step_tool_calls, base_user_input)
                    if resp_text:
                        emotion = self._determine_emotion(tool_calls_executed)
                        return LoopResult(
                            final_text=resp_text,
                            emotion=emotion,
                            tool_calls_executed=tool_calls_executed,
                            steps=step,
                        )

                if route == "command" and step_tool_calls:
                    resp_text = self._command_reply_from_tools(step_tool_calls)
                    if not resp_text:
                        resp_text = self._fallback_text_from_tools(step_tool_calls, base_user_input)
                    if resp_text:
                        emotion = self._determine_emotion(tool_calls_executed)
                        return LoopResult(
                            final_text=resp_text,
                            emotion=emotion,
                            tool_calls_executed=tool_calls_executed,
                            steps=step,
                        )

            # Max steps reached — summarize
            emotion = self._determine_emotion(tool_calls_executed)
            summary = last_text or self._summarize_steps(tool_calls_executed)
            return LoopResult(
                final_text=summary,
                emotion=emotion,
                tool_calls_executed=tool_calls_executed,
                steps=self.MAX_STEPS,
            )
        finally:
            try:
                outer.end(steps=last_step, tools=len(tool_calls_executed))
            except Exception:
                pass

    @staticmethod
    def _needs_tool_action(user_input: str) -> bool:
        """Heuristic: user request likely needs tools (file/web/system)."""
        s = str(user_input or "").strip()
        if not s:
            return False
        # File actions
        if re.search(r"整理|归档|移动|挪到|放到|改名|重命名|批量|文件夹|文件|目录|路径|查找文件|找一下文件|找个文件", s):
            return True
        # Web/info
        if re.search(r"查一下|搜一下|来源|是否真实|核实|辟谣|机票|价格|便宜", s):
            return True
        # System control
        if re.search(r"音量|亮度|wifi|蓝牙|打开应用|启动", s, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _tool_available(tool_defs: list[dict] | None, name: str) -> bool:
        """Return True if a tool schema list contains the given tool name."""
        n = str(name or "").strip()
        if not n or not tool_defs:
            return False
        for td in tool_defs:
            if not isinstance(td, dict):
                continue
            if td.get("type") != "function":
                continue
            fn = td.get("function")
            if isinstance(fn, dict) and str(fn.get("name") or "").strip() == n:
                return True
        return False

    @staticmethod
    def _primitive_tool_hint(user_input: str) -> str:
        """Return a short hint about which primitive tool is most appropriate.

        This is intentionally heuristic and language-oriented; it should only bias
        the model, not hard-route execution.
        """
        s = str(user_input or "").strip()
        low = s.lower()

        # File operations (prefer when both match)
        if re.search(r"整理|归档|移动|挪到|放到|改名|重命名|批量", s):
            return "fs_apply（批量 move/rename/write），必要时先 fs_preview"

        # File discovery
        if re.search(r"找|查找|在哪|路径|目录|文件夹|文件", s):
            return "fs_search（全盘查找文件/文件夹）"

        # System control
        if re.search(r"音量|亮度|wifi|wi-fi|蓝牙|bluetooth|打开应用|启动|关闭应用|退出", low, re.IGNORECASE):
            return "system_control（系统控制），如有现成 shortcut 可用 shortcuts_run"

        # Web / open
        if re.search(r"打开.*网站|官网|网页|浏览器|打开.*\.(com|cn|net|org)", low):
            return "open_website 或 open_url"
        if re.search(r"查一下|搜一下|搜索|找一下|对比|便宜|价格|机票", s):
            return "smart_search / web_fetch / open_url"

        return "fs_search/fs_apply/system_control/open_url/smart_search（按需选择）"

    def _determine_emotion(self, tool_calls: list[dict]) -> str:
        """Determine final emotion based on tool execution results."""
        if not tool_calls:
            return "neutral"
        last = tool_calls[-1]
        if last.get("success"):
            return "happy"
        return "sad"

    @staticmethod
    def _can_parallelize_tool_calls(calls: list[dict]) -> bool:
        """Return True when a batch of tool calls is read-only and independent."""
        if not isinstance(calls, list) or len(calls) <= 1:
            return False
        read_only = {
            "smart_search",
            "search",
            "web_fetch",
            "tavily_search",
            "web_search",
            "get_time",
            "memory_search",
            "system_capabilities",
            "fs_search",
            "fs_preview",
        }
        for tc in calls:
            if not isinstance(tc, dict):
                return False
            n = str(tc.get("name") or "").strip()
            if n not in read_only:
                return False
        return True

    @staticmethod
    def _parallel_metrics(rows: list[dict], wall_ms: float) -> dict[str, float]:
        """Compute observability metrics for a parallel tool batch."""
        vals = []
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            try:
                vals.append(float(r.get("elapsed_ms") or 0.0))
            except Exception:
                vals.append(0.0)
        s = float(sum(vals))
        m = float(max(vals)) if vals else 0.0
        w = float(wall_ms or 0.0)
        saved = max(0.0, s - w)
        speedup = (s / w) if w > 0.0 else 1.0
        return {
            "count": float(len(vals)),
            "sum_ms": s,
            "max_ms": m,
            "wall_ms": w,
            "saved_ms": saved,
            "speedup": speedup,
        }

    @staticmethod
    def _extract_skill_guidance(result_str: str) -> tuple[str | None, str]:
        """Extract a compact, prompt-friendly guidance snippet from skills_read JSON."""
        payload = None
        try:
            payload = json.loads(str(result_str or ""))
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return None, ""

        sname = str(payload.get("name") or "").strip() or None
        content = str(payload.get("content") or "")
        desc = str(payload.get("description") or "")
        title = str(payload.get("title") or sname or "")

        guidance_parts = []
        if title:
            guidance_parts.append(f"# {title}")
        if desc:
            guidance_parts.append(desc)
        if content:
            guidance_parts.append(content)

        guidance = "\n\n".join([p for p in guidance_parts if p.strip()]).strip()
        if len(guidance) > 2000:
            guidance = guidance[:2000] + "\n[...snip...]"

        return sname or title or "skill", guidance

    @staticmethod
    def _score_skill_page(page_text: str, user_request: str) -> int:
        """Very small relevance score for a skills.sh page.

        We extract name/description if present and do token overlap.
        """
        txt = str(page_text or "")
        req = str(user_request or "")
        if not txt or not req:
            return 0

        head = "\n".join(txt.splitlines()[:80]).lower()
        req_low = req.lower()

        # Prefer explicit description/name signals.
        desc = ""
        m = re.search(r"^description:\s*(.+)$", head, re.MULTILINE)
        if m:
            desc = m.group(1).strip()
        name = ""
        m2 = re.search(r"^name:\s*(.+)$", head, re.MULTILINE)
        if m2:
            name = m2.group(1).strip()

        hay = (name + " " + desc + " " + head)

        score = 0
        # Strong signals
        if req_low and req_low in hay:
            score += 8
        # Token overlap
        for tok in re.split(r"\s+", req_low):
            tok = tok.strip()
            if not tok:
                continue
            if tok in hay:
                score += 1

        # Chinese char overlap (coarse)
        if re.search(r"[\u4e00-\u9fff]", req):
            for ch in req:
                if "\u4e00" <= ch <= "\u9fff" and ch in hay:
                    score += 1

        return score

    def _summarize_steps(self, tool_calls: list[dict]) -> str:
        """Summarize executed steps when max iterations reached."""
        if not tool_calls:
            return "已达到最大执行步数，但没有明确结果。"
        parts = []
        for tc in tool_calls:
            status = "✓" if tc.get("success") else "✗"
            parts.append(f"{status} {tc['name']}")
        return f"执行了 {len(tool_calls)} 步操作: " + ", ".join(parts)

    def _respond_from_tools_with_model(self, user_input: str, tool_calls: list[dict]) -> str:
        """Phase-B responder: summarize tool outputs without exposing chain-of-thought."""
        try:
            # Weather-specific guardrail: when all weather fetch tools failed,
            # avoid surfacing raw JSON errors and return a concise fallback.
            if self._is_weather_query(user_input):
                has_success = any(isinstance(tc, dict) and bool(tc.get("success")) for tc in (tool_calls or []))
                if not has_success:
                    city = self._extract_weather_city(user_input)
                    return f"我这次没拿到{city}的天气数据（网络服务暂时不可用）。你可以稍后再试，或让我改用网页来源再查一次。"

            lines = []
            for tc in tool_calls[-3:]:
                if not isinstance(tc, dict):
                    continue
                name = str(tc.get("name") or "").strip()
                ok = bool(tc.get("success"))
                result = str(tc.get("result") or "").strip()
                status = "success" if ok else "failed"
                if len(result) > 1200:
                    result = result[:1200] + "..."
                lines.append(f"- {name} ({status}): {result}")

            if not lines:
                return ""

            system = (
                "你是结果整理助手。根据工具输出直接回答用户问题。"
                "不要解释工具调用过程，不要编造。"
                "如果信息不足，明确说还缺什么。"
            )
            user = (
                f"用户问题: {user_input}\n\n"
                f"工具输出:\n{chr(10).join(lines)}\n\n"
                "请用中文给出简洁结论。"
            )
            t0 = time.monotonic()
            resp = self.model.generate(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=None,
                max_tokens=220,
            )
            text = str(resp.text or "").strip()
            log(
                "loop",
                "model.responder",
                elapsed_ms=f"{(time.monotonic()-t0)*1000:.1f}",
                text_len=len(text),
            )
            return text
        except Exception:
            return ""

    @staticmethod
    def _fallback_text_from_tools(tool_calls: list[dict], user_input: str = "") -> str:
        """Build a user-facing reply when model returns empty text.

        This avoids silent turns when tools already produced useful output.
        """
        for tc in reversed(tool_calls or []):
            if not isinstance(tc, dict) or not tc.get("success"):
                continue
            name = str(tc.get("name") or "").strip()
            result = str(tc.get("result") or "").strip()
            if not result:
                continue

            if name == "smart_search":
                try:
                    payload = json.loads(result)
                    items = payload.get("results") if isinstance(payload, dict) else None
                    if isinstance(items, list) and items:
                        q = str(user_input or "")
                        low_q = q.lower()

                        def _domain_of(it: dict) -> str:
                            u = str(it.get("url") or "").strip().lower()
                            try:
                                return urllib.parse.urlparse(u).netloc
                            except Exception:
                                return ""

                        top = items[0] if isinstance(items[0], dict) else {}
                        if any(k in q for k in ("视频", "最新视频", "频道", "博主", "up主")) or any(
                            k in low_q for k in ("youtube", "youtuber", "video", "channel", "bilibili")
                        ):
                            preferred_domains = ["youtube.com", "youtu.be"]
                            if any(k in q for k in ("b站", "哔哩", "哔哩哔哩")) or "bilibili" in low_q:
                                preferred_domains = ["bilibili.com"]
                            for it in items:
                                if not isinstance(it, dict):
                                    continue
                                d = _domain_of(it)
                                if any(p in d for p in preferred_domains):
                                    top = it
                                    break

                        title = str(top.get("title") or "").strip()
                        url = str(top.get("url") or "").strip()
                        snippet = str(top.get("content") or top.get("snippet") or "").strip()
                        if any(k in q for k in ("视频", "最新视频", "youtube", "b站", "哔哩")):
                            if title and url:
                                return f"我找到一个最新视频候选：{title}。链接：{url}"
                            if title:
                                return f"我找到一个最新视频候选：{title}。"
                        if title and snippet:
                            return f"我查到了：{title}。{snippet[:120]}"
                        if title:
                            return f"我查到了：{title}。"
                except Exception:
                    pass

            if name == "web_fetch":
                # Try weather-specific concise formatter first.
                is_weather = AgenticLoop._is_weather_query(user_input)
                city = AgenticLoop._extract_weather_city(user_input)
                concise_weather = AgenticLoop._format_weather_from_wttr_result(
                    tc,
                    city,
                    AgenticLoop._extract_weather_day_offset(user_input),
                )
                if concise_weather:
                    return concise_weather
                try:
                    payload = json.loads(result)
                    content = str((payload or {}).get("content") or "").strip()
                    if content:
                        # Keep concise and avoid reading long irrelevant blocks.
                        cleaned = re.sub(r"\s+", " ", content)
                        if is_weather:
                            return f"我查到了{city}天气信息：{cleaned[:80]}"
                        return f"我已抓取到信息：{cleaned[:80]}"
                except Exception:
                    pass

            return f"我已执行{name}，结果是：{result[:140]}"

        return ""

    @staticmethod
    def _infer_command_tool_call(user_input: str) -> dict | None:
        """Infer a deterministic tool call for obvious command intents."""
        call, confidence = AgenticLoop._infer_command_tool_call_scored(user_input)
        if confidence < 0.5:
            return None
        return call

    @staticmethod
    def _infer_command_tool_call_scored(user_input: str) -> tuple[dict | None, float]:
        """Infer deterministic command call with confidence score [0, 1]."""
        s = str(user_input or "")
        low = s.lower()

        def _has_any(text: str, words: tuple[str, ...]) -> bool:
            return any(w in text for w in words)

        def _confidence(base: float) -> float:
            conf = float(base)
            if _has_any(s, ("帮我", "请", "麻烦", "把", "调", "打开", "关闭", "关掉", "开启")):
                conf += 0.2
            if _has_any(s, ("吗", "什么", "怎么", "为何", "意思", "介绍", "教程", "查询", "搜索", "了解", "是什么")):
                conf -= 0.6
            if "?" in s or "？" in s:
                conf -= 0.2
            return max(0.0, min(1.0, conf))

        if "亮度" in s or _has_any(s, ("太暗", "太亮", "屏幕暗", "屏幕亮")):
            action = "up"
            # Brightness intent from natural phrases
            if _has_any(s, ("太亮", "刺眼", "晃眼", "降低", "调低", "调暗", "暗一点")):
                action = "down"
            elif _has_any(s, ("太暗", "看不清", "调高", "调亮", "亮一点")):
                action = "up"
            return ({"name": "system_control", "arguments": {"target": "brightness", "action": action}}, _confidence(0.8))

        if "音量" in s or "声音" in s or _has_any(s, ("太小声", "太大声", "太吵", "听不清")):
            action = "up"
            if _has_any(s, ("太大声", "太吵", "降低", "调低", "小一点", "轻一点")):
                action = "down"
            if "静音" in s or "mute" in low:
                action = "mute"
            elif _has_any(s, ("太小声", "听不清", "大一点", "响一点", "调高")):
                action = "up"
            return ({"name": "system_control", "arguments": {"target": "volume", "action": action}}, _confidence(0.8))

        if "蓝牙" in s:
            action = "off" if any(k in s for k in ("关", "关闭", "关掉")) else "on"
            return ({"name": "system_control", "arguments": {"target": "bluetooth", "action": action}}, _confidence(0.75))

        if "wifi" in low or "wi-fi" in low or "无线网" in s:
            action = "off" if any(k in s for k in ("关", "关闭", "关掉")) else "on"
            return ({"name": "system_control", "arguments": {"target": "wifi", "action": action}}, _confidence(0.75))

        return (None, 0.0)

    @staticmethod
    def _command_reply_from_tools(tool_calls: list[dict]) -> str:
        """Return concise user-facing text for command route."""
        for tc in reversed(tool_calls or []):
            if not isinstance(tc, dict):
                continue
            name = str(tc.get("name") or "")
            ok = bool(tc.get("success"))
            if name != "system_control":
                continue
            args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
            target = str((args or {}).get("target") or "")
            action = str((args or {}).get("action") or "")
            if not ok:
                return "系统操作失败了，要我再试一次吗？"
            if target == "brightness":
                return "亮度已调高。" if action == "up" else "亮度已调低。"
            if target == "volume":
                if action == "mute":
                    return "已静音。"
                return "音量已调高。" if action == "up" else "音量已调低。"
            if target == "wifi":
                return "Wi-Fi 已打开。" if action == "on" else "Wi-Fi 已关闭。"
            if target == "bluetooth":
                return "蓝牙已打开。" if action == "on" else "蓝牙已关闭。"
            return "系统设置已完成。"
        return ""

    @staticmethod
    def _is_weather_query(user_input: str) -> bool:
        s = str(user_input or "")
        return "天气" in s or "weather" in s.lower()

    @staticmethod
    def _extract_weather_day_offset(user_input: str) -> int:
        s = str(user_input or "")
        if any(k in s for k in ("明天", "tomorrow")):
            return 1
        return 0

    @staticmethod
    def _extract_weather_city(user_input: str) -> str:
        s = str(user_input or "").strip()
        m = re.search(r"([\u4e00-\u9fffA-Za-z·\-]{1,20})\s*(的)?\s*天气", s)
        if m:
            city = str(m.group(1) or "").strip(" ，,。.!！?")
            # remove common fillers and temporal words accidentally captured
            city = re.sub(r"^(帮我查一下|帮我查下|查一下|查下|查询|帮我|请|麻烦|帮忙|希望|想|我想|我想要)", "", city)
            city = re.sub(r"^(今天|明天|后天)", "", city)
            city = city.strip(" ，,。.!！?")
            city = city.strip()
            if city:
                return city
        return "上海"

    @staticmethod
    def _normalize_city_for_weather_api(city: str) -> str:
        c = str(city or "").strip()
        mapping = {
            "尼斯": "Nice",
            "上海": "Shanghai",
            "北京": "Beijing",
            "广州": "Guangzhou",
            "深圳": "Shenzhen",
            "杭州": "Hangzhou",
            "南京": "Nanjing",
            "成都": "Chengdu",
            "武汉": "Wuhan",
            "重庆": "Chongqing",
            "西安": "Xi'an",
            "天津": "Tianjin",
            "香港": "Hong Kong",
            "澳门": "Macau",
            "台北": "Taipei",
        }
        return mapping.get(c, c or "Shanghai")

    @staticmethod
    def _format_weather_from_wttr_result(tool_call: dict, city: str, day_offset: int = 0) -> str:
        """Parse wttr.in JSON from web_fetch tool result into a concise reply."""
        try:
            raw = str((tool_call or {}).get("result") or "")
            payload = json.loads(raw)
            content = payload.get("content") if isinstance(payload, dict) else None
            data = json.loads(content) if isinstance(content, str) else None
            if not isinstance(data, dict):
                return ""

            cc = (data.get("current_condition") or [{}])[0]
            weather_days = data.get("weather") or []
            idx = max(0, min(int(day_offset), len(weather_days) - 1)) if weather_days else 0
            day = weather_days[idx] if weather_days else {}

            desc = ""
            wdesc = cc.get("weatherDesc")
            if isinstance(wdesc, list) and wdesc:
                d0 = wdesc[0]
                if isinstance(d0, dict):
                    desc = str(d0.get("value") or "").strip()

            temp_c = str(cc.get("temp_C") or "").strip()
            feels = str(cc.get("FeelsLikeC") or "").strip()
            mint = str(day.get("mintempC") or "").strip()
            maxt = str(day.get("maxtempC") or "").strip()
            humidity = str(cc.get("humidity") or "").strip()

            when = "明天" if int(day_offset) == 1 else "今天"
            city_name = str(city or "该城市").strip()

            parts = [f"{city_name}{when}"]
            if desc:
                parts.append(desc)
            if mint or maxt:
                if mint and maxt:
                    parts.append(f"气温{mint}到{maxt}度")
                elif maxt:
                    parts.append(f"最高{maxt}度")
                elif mint:
                    parts.append(f"最低{mint}度")
            elif temp_c:
                parts.append(f"当前约{temp_c}度")
            if feels:
                parts.append(f"体感{feels}度")
            if humidity:
                parts.append(f"湿度{humidity}%")
            return "，".join(parts) + "。"
        except Exception:
            return ""

    @staticmethod
    def _remove_repetition(text: str) -> str:
        """Remove repeated tail from text."""
        if len(text) < 20:
            return text
        # Find the first repeated 10-char block and truncate there
        for i in range(len(text) - 10):
            sub = text[i:i + 10]
            first = text.find(sub)
            second = text.find(sub, first + 1)
            if second != -1 and second != first:
                return text[:second].rstrip()
        return text

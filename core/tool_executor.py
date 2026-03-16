"""
Tool Executor — 多格式解析、安全分级、审计日志

通过 Tool_Registry 查找和执行工具，增加：
- 多格式工具调用解析：JSON > Pythonic > >>>ACTION:
- ToolResult 结构化返回
- 安全分级：从 Registry 读取
- 审计日志：DANGEROUS 操作写入 audit.log
- 执行日志：所有操作写入 tool_log.jsonl
"""

import json
import os
import re
import time
import datetime
import logging
import difflib
import ast
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

from core.trace import log

if TYPE_CHECKING:
    from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    name: str
    success: bool
    result: str
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    elapsed_ms: float = 0.0


class ToolExecutor:
    """工具执行器：通过 Tool_Registry 查找和执行工具"""

    def __init__(self, tool_registry: "ToolRegistry", workspace_dir: str = "~/.kage"):
        self.registry = tool_registry
        workspace = os.path.expanduser(workspace_dir)
        os.makedirs(workspace, exist_ok=True)

        self.tool_log_file = os.path.join(workspace, "tool_log.jsonl")
        self.audit_log_file = os.path.join(workspace, "audit.log")

        logger.info("ToolExecutor initialized — %d registered tools", 
                    len(self.registry.get_tool_names()))

    # ------------------------------------------------------------------
    # Parsing — multi-format tool call extraction
    # ------------------------------------------------------------------

    def parse_tool_calls(self, text: str) -> list[dict]:
        """Multi-format parse: JSON > Pythonic > >>>ACTION:

        Returns list of {"name": str, "arguments": dict}.
        Returns empty list if no format matches.
        """
        if not text or not text.strip():
            return []

        # 1) JSON format (OpenAI function calling style)
        json_results = self._parse_json_format(text)
        if json_results:
            return json_results

        # 1.5) Bracket format: <|tool_call_start|>[tool(arg=...)]<|tool_call_end|>
        bracket_results = self._parse_bracket_format(text)
        if bracket_results:
            return bracket_results

        # 2) >>>ACTION: format (legacy)
        action_results = self._parse_action_format(text)
        if action_results:
            return action_results

        # 3) Standalone Pythonic call: func(arg="val")
        pythonic_results = self._parse_standalone_pythonic(text)
        if pythonic_results:
            return pythonic_results

        return []

    def _parse_bracket_format(self, text: str) -> list[dict]:
        results: list[dict] = []
        if not text:
            return results
        pattern = re.compile(r"<\|tool_call_start\|>\s*\[(.*?)\]\s*<\|tool_call_end\|>", re.DOTALL)
        for m in pattern.finditer(text):
            inner = (m.group(1) or "").strip()
            if not inner:
                continue
            call = self._parse_python_call_string(inner)
            if call:
                results.append(call)
        return results

    def _parse_python_call_string(self, call_str: str) -> dict | None:
        """Parse a string like tool(arg="x") into {name, arguments}.

        Supports hyphenated tool names by normalizing '-' to '_'.
        """
        s = str(call_str or "").strip()
        if not s:
            return None
        # Normalize name for Python parsing
        name = s.split("(", 1)[0].strip()
        norm_name = name.replace("-", "_")
        if "(" in s:
            expr = norm_name + "(" + s.split("(", 1)[1]
        else:
            expr = norm_name + "()"
        try:
            node = ast.parse(expr, mode="eval")
        except Exception:
            return None
        if not isinstance(node.body, ast.Call):
            return None
        if not isinstance(node.body.func, ast.Name):
            return None
        parsed_name = str(node.body.func.id)
        if not self.registry.has_tool(parsed_name):
            alt = self._fuzzy_match_tool_name(parsed_name)
            if not alt:
                return None
            parsed_name = alt
        args: dict = {}
        for kw in node.body.keywords or []:
            if kw.arg is None:
                continue
            try:
                args[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                # Fallback: best-effort string
                try:
                    args[kw.arg] = getattr(kw.value, "value", None)
                except Exception:
                    args[kw.arg] = None
        args = self._normalize_arguments(parsed_name, args)
        return {"name": parsed_name, "arguments": args}

    def _fuzzy_match_tool_name(self, name: str) -> str | None:
        """Best-effort fuzzy match for hallucinated tool names.

        We intentionally do NOT fuzzy-map to `exec` because it is overly powerful.
        """
        raw = str(name or "").strip()
        if not raw:
            return None
        if self.registry.has_tool(raw):
            return raw

        candidates = [n for n in (self.registry.get_tool_names() or []) if n != "exec"]
        if not candidates:
            return None

        matches = difflib.get_close_matches(raw, candidates, n=1, cutoff=0.84)
        return matches[0] if matches else None

    def _normalize_arguments(self, name: str, arguments: dict) -> dict:
        """Normalize common hallucinated argument keys.

        This is a conservative, whitelist-based mapping.
        """
        if not isinstance(arguments, dict):
            return {}
        args = dict(arguments)

        def _first_value(d: dict, keys: list[str]):
            for k in keys:
                if k in d and d.get(k) not in (None, ""):
                    return d.get(k)
            return None

        if name == "exec":
            cmd = _first_value(args, ["command", "cmd", "shell", "bash"]) 
            if cmd is not None:
                args = {"command": cmd, "timeout": args.get("timeout", args.get("time", args.get("seconds", 30)))}
            return args

        if name == "open_url":
            url = _first_value(args, ["url", "link", "href", "website"]) 
            if url is not None:
                return {"url": url}
            return args

        if name == "skills_find_remote":
            q = _first_value(args, ["query", "q", "keyword", "keywords", "text"]) 
            if q is not None:
                out = {"query": q}
                if "max_results" in args:
                    out["max_results"] = args.get("max_results")
                return out
            return args

        if name == "skills_install":
            repo = _first_value(args, ["repo", "repository", "package", "url"]) 
            skill = _first_value(args, ["skill", "name", "skill_name"]) 
            out = dict(args)
            if repo is not None:
                out["repo"] = repo
            if skill is not None:
                out["skill"] = skill
            return out

        if name == "fs_move":
            src = _first_value(args, ["src", "source", "from", "path"]) 
            dest_dir = _first_value(args, ["dest_dir", "dest", "dst", "to", "destination", "target_dir"]) 
            out = dict(args)
            if src is not None:
                out["src"] = src
            if dest_dir is not None:
                out["dest_dir"] = dest_dir
            return out

        if name == "fs_rename":
            path = _first_value(args, ["path", "src", "from"]) 
            new_name = _first_value(args, ["new_name", "to", "name", "new"]) 
            out = dict(args)
            if path is not None:
                out["path"] = path
            if new_name is not None:
                out["new_name"] = new_name
            return out

        if name == "fs_write":
            path = _first_value(args, ["path", "file", "filename", "to"]) 
            content = _first_value(args, ["content", "text", "body", "data"]) 
            out = dict(args)
            if path is not None:
                out["path"] = path
            if content is not None:
                out["content"] = content
            return out

        if name == "fs_trash":
            path = _first_value(args, ["path", "src", "target", "file"]) 
            if path is not None:
                return {"path": path}
            return args

        if name == "fs_apply":
            ops = args.get("ops")
            if not isinstance(ops, list):
                return args
            norm_ops: list[dict] = []
            for op in ops:
                if not isinstance(op, dict):
                    continue
                kind = str(op.get("op") or "").strip().lower()
                # Allow a tiny set of synonyms.
                kind_map = {
                    "mv": "move",
                    "move": "move",
                    "rename": "rename",
                    "rn": "rename",
                    "write": "write",
                    "save": "write",
                    "trash": "trash",
                    "delete": "trash",
                    "remove": "trash",
                }
                kind = kind_map.get(kind, kind)
                if kind == "move":
                    src = _first_value(op, ["src", "source", "from", "path"]) 
                    dest_dir = _first_value(op, ["dest_dir", "dest", "dst", "to", "destination", "target_dir"]) 
                    if src is None or dest_dir is None:
                        continue
                    norm_ops.append({"op": "move", "src": src, "dest_dir": dest_dir})
                elif kind == "rename":
                    path = _first_value(op, ["path", "src", "from"]) 
                    new_name = _first_value(op, ["new_name", "to", "name", "new"]) 
                    if path is None or new_name is None:
                        continue
                    norm_ops.append({"op": "rename", "path": path, "new_name": new_name})
                elif kind == "write":
                    path = _first_value(op, ["path", "file", "filename", "to"]) 
                    content = _first_value(op, ["content", "text", "body", "data"]) 
                    if path is None or content is None:
                        continue
                    norm_ops.append({"op": "write", "path": path, "content": content})
                elif kind == "trash":
                    path = _first_value(op, ["path", "src", "target", "file"]) 
                    if path is None:
                        continue
                    norm_ops.append({"op": "trash", "path": path})

            out = dict(args)
            out["ops"] = norm_ops
            return out

        return args

    def _parse_json_format(self, text: str) -> list[dict]:
        """Parse JSON tool call format."""
        results = []
        
        # Try to find JSON objects in the text
        # Pattern 1: {"name": "...", "arguments": {...}}
        pattern = r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"arguments"\s*:\s*(\{[^{}]*\})[^{}]*\}'
        for m in re.finditer(pattern, text, re.DOTALL):
            try:
                name = m.group(1)
                if not self.registry.has_tool(name):
                    alt = self._fuzzy_match_tool_name(name)
                    if alt:
                        name = alt
                args = json.loads(m.group(2))
                results.append({"name": name, "arguments": args})
            except json.JSONDecodeError:
                continue
        
        if results:
            return results
        
        # Pattern 2: Bare JSON object with tool name as key
        # {"tool_name": {"arg1": "val1"}}
        try:
            # Find JSON-like structures
            for m in re.finditer(r'\{[^{}]+\}', text):
                try:
                    obj = json.loads(m.group())
                    if isinstance(obj, dict) and len(obj) == 1:
                        name = list(obj.keys())[0]
                        if not self.registry.has_tool(name):
                            alt = self._fuzzy_match_tool_name(name)
                            if alt:
                                name = alt
                        if self.registry.has_tool(name):
                            args = obj[name] if isinstance(obj[name], dict) else {}
                            results.append({"name": name, "arguments": args})
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
        
        return results

    def _parse_action_format(self, text: str) -> list[dict]:
        """Parse >>>ACTION: tool_name arg1=val1 arg2=val2 format."""
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith(">>>ACTION:"):
                continue
            rest = line[len(">>>ACTION:"):].strip()
            parts = rest.split(None, 1)
            if not parts:
                continue
            name = parts[0]
            if not self.registry.has_tool(name):
                alt = self._fuzzy_match_tool_name(name)
                if alt:
                    name = alt
            arguments = {}
            if len(parts) > 1:
                # Parse key=value pairs
                for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', parts[1]):
                    arguments[m.group(1)] = m.group(2)
                for m in re.finditer(r"(\w+)\s*=\s*'([^']*)'", parts[1]):
                    if m.group(1) not in arguments:
                        arguments[m.group(1)] = m.group(2)
                # Bare key=value (no quotes)
                for m in re.finditer(r'(\w+)\s*=\s*(\S+)', parts[1]):
                    if m.group(1) not in arguments:
                        arguments[m.group(1)] = m.group(2)
            results.append({"name": name, "arguments": arguments})
        return results

    def _parse_standalone_pythonic(self, text: str) -> list[dict]:
        """Parse standalone func(arg="val") calls."""
        results = []
        pattern = r'(\w+)\s*\(([^)]*)\)'
        for m in re.finditer(pattern, text):
            name = m.group(1)
            if not self.registry.has_tool(name):
                alt = self._fuzzy_match_tool_name(name)
                if not alt:
                    continue
                name = alt
            args_str = m.group(2).strip()
            arguments = {}
            if args_str:
                for kv in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', args_str):
                    arguments[kv.group(1)] = kv.group(2)
                for kv in re.finditer(r"(\w+)\s*=\s*'([^']*)'", args_str):
                    if kv.group(1) not in arguments:
                        arguments[kv.group(1)] = kv.group(2)
            results.append({"name": name, "arguments": arguments})
        return results

    # ------------------------------------------------------------------
    # Security classification
    # ------------------------------------------------------------------

    def get_security_level(self, tool_name: str) -> str:
        """Return 'SAFE' or 'DANGEROUS' for a tool name."""
        return self.registry.get_security_level(tool_name)

    def _requires_delete_confirmation(self, name: str, arguments: dict) -> bool:
        """Return True if this invocation performs deletion-like behavior."""
        if name == "fs_trash":
            return True
        if name == "fs_apply":
            ops = (arguments or {}).get("ops")
            if isinstance(ops, list):
                for op in ops:
                    if isinstance(op, dict) and str(op.get("op") or "").strip().lower() == "trash":
                        return True
        if name == "exec":
            cmd = str((arguments or {}).get("command") or "").strip().lower()
            # Very conservative: only gate obvious deletion commands.
            delete_tokens = [" rm ", "rm -", "rm\t", "rm\n", " rm$", "rmdir ", "trash ", "delete "]
            if cmd.startswith("rm ") or cmd.startswith("rm-"):
                return True
            for tok in delete_tokens:
                if tok in cmd:
                    return True
        return False

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        arguments: dict,
        require_confirmation: Optional[Callable[..., Awaitable[bool]]] = None,
    ) -> ToolResult:
        """Execute a tool call with safety checks and logging.

        For DANGEROUS tools, calls require_confirmation callback if provided.
        """
        start = time.monotonic()
        try:
            log("tool", "execute.start", name=str(name), arg_keys=sorted(list((arguments or {}).keys())) if isinstance(arguments, dict) else [])
        except Exception:
            pass

        # Best-effort fuzzy match for hallucinated tool name
        orig_name = str(name or "").strip()
        if orig_name and not self.registry.has_tool(orig_name):
            alt = self._fuzzy_match_tool_name(orig_name)
            if alt:
                name = alt

        if not isinstance(arguments, dict):
            arguments = {}
        # Normalize argument keys before any security checks.
        arguments = self._normalize_arguments(str(name), arguments)

        # Check if tool exists
        handler = self.registry.get_handler(name)
        if handler is None:
            elapsed = (time.monotonic() - start) * 1000
            result = ToolResult(
                name=str(name), success=False,
                result="",
                error_type="UnknownTool",
                error_message=f"未知工具: {orig_name}",
                elapsed_ms=elapsed,
            )
            self.log_execution(result, arguments)
            return result

        # Security check
        level = self.get_security_level(name)
        # Policy: only deletion requires confirmation. Upgrade level dynamically.
        if level != "DANGEROUS" and self._requires_delete_confirmation(name, arguments or {}):
            level = "DANGEROUS"
        if level == "DANGEROUS":
            # Allow bypass if caller marked confirmed.
            if isinstance(arguments, dict) and arguments.get("confirmed") is True:
                pass
            elif require_confirmation is not None:
                try:
                    confirmed = await require_confirmation(name, arguments)
                    if not confirmed:
                        elapsed = (time.monotonic() - start) * 1000
                        result = ToolResult(
                            name=name, success=False,
                            result="用户拒绝执行该操作",
                            error_type="UserDenied",
                            error_message="用户拒绝执行危险操作",
                            elapsed_ms=elapsed,
                        )
                        self.log_execution(result, arguments)
                        self._write_audit_log(result, arguments)
                        return result
                except Exception as exc:
                    logger.warning("Confirmation callback failed: %s", exc)
            else:
                elapsed = (time.monotonic() - start) * 1000
                preview = json.dumps(arguments or {}, ensure_ascii=False)
                result = ToolResult(
                    name=name,
                    success=False,
                    result="",
                    error_type="NeedConfirmation",
                    error_message=f"需要确认后才能执行: {name} {preview}",
                    elapsed_ms=elapsed,
                )
                self.log_execution(result, arguments)
                self._write_audit_log(result, arguments)
                return result

        # Execute via handler
        try:
            raw_result = handler(**arguments)
            elapsed = (time.monotonic() - start) * 1000
            result = ToolResult(
                name=name, success=True,
                result=str(raw_result),
                elapsed_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            result = ToolResult(
                name=name, success=False,
                result="",
                error_type=type(exc).__name__,
                error_message=str(exc),
                elapsed_ms=elapsed,
            )

        # Log execution
        self.log_execution(result, arguments)

        try:
            log(
                "tool",
                "execute.end",
                name=result.name,
                success=result.success,
                elapsed_ms=f"{result.elapsed_ms:.1f}",
                error_type=result.error_type,
            )
        except Exception:
            pass

        # Audit log for DANGEROUS operations
        if level == "DANGEROUS":
            self._write_audit_log(result, arguments)

        return result

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_execution(self, result: ToolResult, arguments: dict | None = None) -> None:
        """Append execution record to tool_log.jsonl."""
        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "name": result.name,
            "arguments": arguments or {},
            "success": result.success,
            "result_summary": result.result[:200] if result.result else "",
            "elapsed_ms": result.elapsed_ms,
        }
        if not result.success:
            record["error_type"] = result.error_type
            record["error_message"] = result.error_message

        try:
            with open(self.tool_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error("Failed to write tool log: %s", exc)

    def _write_audit_log(self, result: ToolResult, arguments: dict | None = None) -> None:
        """Append DANGEROUS operation to audit.log."""
        ts = datetime.datetime.now().isoformat()
        status = "SUCCESS" if result.success else "FAILED"
        summary = result.result[:100] if result.result else (result.error_message or "")
        args_str = json.dumps(arguments or {}, ensure_ascii=False)
        line = f"[{ts}] DANGEROUS {result.name} {args_str} -> {status} \"{summary}\"\n"

        try:
            with open(self.audit_log_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            logger.error("Failed to write audit log: %s", exc)

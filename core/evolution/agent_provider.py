"""
EvoLab E0: real Kage execution-chain provider.

This module wires the frozen production chain (``PromptBuilder`` + ``ToolExecutor``
+ ``AgenticLoop``, with a ``ModelProvider`` obtained from ``ModelBroker``) into the
E0 experiment kernel, so baseline runs exercise the same code paths the shipped
assistant uses instead of a self-written file-writing stub.

Design notes (master plan v2.1, E0):
  * The candidate/agent side only ever sees the task instruction and the task
    workspace. Scoring criteria and expected answers stay in the parent process.
  * Tools are workspace-confined: ``read_file``/``write_file``/``list_files``
    resolve inside the run workspace only.
  * Token usage is taken from provider-reported ``usage`` and settled against the
    budget; when a provider reports nothing the kernel settles conservatively.
  * A live run must never silently fall back to the fake provider. Missing
    credentials raise ``ProviderUnavailableError`` before any run starts, and a
    transport failure surfaces as an observable run failure.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from core.agentic_loop import AgenticLoop
from core.model_provider import ModelProvider, ModelResponse
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolDefinition, ToolRegistry

KAGE_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Frozen experiment identity: no persona, no user memory, no companion behaviour
# leaks into the measurement. The prompt is part of the frozen baseline.
EXPERIMENT_SOUL = (
    "You are Kage running a frozen evaluation task.\n"
    "Complete the user's request using only the provided tools.\n"
    "All file paths are relative to the task workspace; never use absolute paths.\n"
    "Call one tool at a time. When the requested output file is written and correct, "
    "reply with a short summary and stop calling tools."
)

MAX_TOOL_RESULT_CHARS = 20_000


class ProviderUnavailableError(RuntimeError):
    """Raised before a live run starts when the configured provider cannot be used."""


class ModelCallLimitExceeded(RuntimeError):
    """Raised when a single chain invocation exceeds its model-call guard."""


# ---------------------------------------------------------------------------
# Workspace confinement and tools
# ---------------------------------------------------------------------------
def resolve_in_workspace(workspace: Path | str, relative: Any) -> Path:
    """Resolve a workspace-relative path, refusing escapes and absolute paths."""
    root = Path(workspace).resolve()
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("path must be a non-empty workspace-relative string")
    if Path(relative).is_absolute():
        raise ValueError("absolute paths are not allowed in the task workspace")
    target = (root / relative).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError("path escapes the task workspace")
    return target


def build_workspace_registry(workspace: Path | str) -> ToolRegistry:
    """Frozen per-run registry: three workspace-confined filesystem tools."""

    def read_file(path: str) -> str:
        try:
            target = resolve_in_workspace(workspace, path)
        except ValueError as exc:
            return json.dumps({"success": False, "error": str(exc)})
        if not target.exists():
            return json.dumps({"success": False, "error": f"File not found: {path}"})
        if target.is_dir():
            return json.dumps({"success": False, "error": f"Not a file: {path}"})
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - surfaced to the model
            return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})
        return json.dumps({"success": True, "path": path,
                           "content": content[:MAX_TOOL_RESULT_CHARS]}, ensure_ascii=False)

    def write_file(path: str, content: str) -> str:
        try:
            target = resolve_in_workspace(workspace, path)
        except ValueError as exc:
            return json.dumps({"success": False, "error": str(exc)})
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - surfaced to the model
            return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})
        return json.dumps({"success": True, "path": path,
                           "bytes_written": len(str(content).encode("utf-8"))})

    def list_files() -> str:
        root = Path(workspace).resolve()
        entries = sorted(
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
        )
        return json.dumps({"success": True, "files": entries}, ensure_ascii=False)

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_file",
        description=("Read a UTF-8 text file from the task workspace. "
                     "Use this before transforming data."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"}},
            "required": ["path"]},
        handler=read_file,
    ))
    registry.register(ToolDefinition(
        name="write_file",
        description=("Write text to a file in the task workspace, creating parent "
                     "directories. Use this to save the final result."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"},
            "content": {"type": "string", "description": "Full file content to write"}},
            "required": ["path", "content"]},
        handler=write_file,
    ))
    registry.register(ToolDefinition(
        name="list_files",
        description="List files currently present in the task workspace.",
        parameters={"type": "object", "properties": {}},
        handler=list_files,
    ))
    return registry


class ExperimentIdentityStore:
    """Minimal frozen identity so PromptBuilder can build a hermetic system prompt."""

    def __init__(self, soul: str = EXPERIMENT_SOUL) -> None:
        self._soul = soul

    def load_soul(self) -> str:
        return self._soul

    def load_user(self) -> str:
        return ""

    def load_tools_notes(self) -> str:
        return ""


class HistorySession:
    """Read-only history source for AgenticLoop (it only calls get_history())."""

    def __init__(self, history: list[dict[str, Any]] | None = None) -> None:
        self._history = list(history or [])

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)


# ---------------------------------------------------------------------------
# Metering wrapper (the plan's "billing wrapper": no second cloud SDK)
# ---------------------------------------------------------------------------
class MeteredProvider(ModelProvider):
    """Delegates to a real provider while recording per-call usage and errors."""

    def __init__(self, inner: ModelProvider, *, label: str = "",
                 max_calls: int = 8) -> None:
        self.inner = inner
        self.label = label or type(inner).__name__
        self.max_calls = max(1, int(max_calls))
        self.calls: list[dict[str, Any]] = []

    def generate(self, messages: list[dict], tools: list[dict] | None = None,
                 max_tokens: int = 200, temperature: float = 0.7) -> ModelResponse:
        if len(self.calls) >= self.max_calls:
            raise ModelCallLimitExceeded(
                f"model call guard reached ({self.max_calls}) for chain invocation"
            )
        started = time.monotonic()
        response = self.inner.generate(messages=messages, tools=tools,
                                       max_tokens=max_tokens, temperature=temperature)
        self.calls.append({
            "index": len(self.calls) + 1,
            "usage": dict(getattr(response, "usage", {}) or {}),
            "error": getattr(response, "error", None),
            "tool_calls": len(getattr(response, "tool_calls", []) or []),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        })
        return response

    @property
    def totals(self) -> dict[str, Any]:
        input_tokens = sum(int(c["usage"].get("input_tokens", 0)) for c in self.calls)
        output_tokens = sum(int(c["usage"].get("output_tokens", 0)) for c in self.calls)
        reported = [c for c in self.calls if c["usage"]]
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "api_calls": len(self.calls),
            "calls_with_reported_usage": len(reported),
            "errors": [c["error"] for c in self.calls if c["error"]],
        }


# ---------------------------------------------------------------------------
# The chain provider
# ---------------------------------------------------------------------------
class KageChainProvider:
    """``generate_step`` implementation backed by the real Kage agent chain.

    One ``generate_step`` call == one frozen-chain invocation
    (``AgenticLoop.run``), which itself may perform several model/tool steps.
    The kernel still owns workspace isolation, wall-clock timeout, budget
    settlement, journaling and external scoring.
    """

    #: Reservation hint (input_cap, output_cap) for one chain invocation.
    RESERVATION_INPUT_CAP = 8_000
    RESERVATION_OUTPUT_CAP = 2_000

    def __init__(
        self,
        model_provider: ModelProvider,
        *,
        provider_mode: str = "live",
        model_label: str = "",
        provider_label: str = "",
        max_model_calls: int = 6,
        agentic_loop_cls: type[AgenticLoop] = AgenticLoop,
    ) -> None:
        self.provider_mode = provider_mode
        self.model_label = model_label or type(model_provider).__name__
        self.provider_label = provider_label or type(model_provider).__name__
        self.max_model_calls = max(1, int(max_model_calls))
        self.agentic_loop_cls = agentic_loop_cls
        self._model = MeteredProvider(model_provider, label=self.provider_label,
                                      max_calls=self.max_model_calls)
        # Kept for interface parity with the fake provider.
        self.calls = 0
        self.call_log: list[dict[str, Any]] = []
        self.last_chain: dict[str, Any] = {}

    # -- kernel-facing API -------------------------------------------------
    def reservation_hint(self) -> tuple[int, int]:
        return (self.RESERVATION_INPUT_CAP, self.RESERVATION_OUTPUT_CAP)

    def cache_identity(self) -> dict[str, Any]:
        """Execution-affecting settings for journal resume, without credentials."""
        return {
            "provider_mode": self.provider_mode,
            "provider_class": self.provider_label,
            "model": self.model_label,
            "max_model_calls": self.max_model_calls,
            "agentic_loop": self.agentic_loop_cls.__name__,
        }

    def metadata(self) -> dict[str, Any]:
        """Static description of the frozen chain (recorded per run)."""
        return {
            "provider_mode": self.provider_mode,
            "provider_class": self.provider_label,
            "model": self.model_label,
            "model_call_guard": self.max_model_calls,
            "agentic_loop": self.agentic_loop_cls.__name__,
            "agentic_loop_max_steps": int(getattr(self.agentic_loop_cls, "MAX_STEPS", 0)),
            "tool_registry": "ToolRegistry(workspace-scoped: read_file/write_file/list_files)",
            "prompt_builder": "PromptBuilder(prune_tools=False, frozen experiment identity)",
            "tool_executor": "ToolExecutor",
            "environment": environment_info(),
        }

    def generate_step(
        self,
        task_def: dict[str, Any],
        step: int,
        history: list[dict[str, Any]],
        workspace_dir: Path,
    ) -> dict[str, Any]:
        self.calls += 1
        task_id = str(task_def.get("task_id") or "")
        self.call_log.append({"task_id": task_id, "step": step})

        instruction = str(task_def.get("instruction") or "").strip()
        if not instruction:
            raise RuntimeError("task has no instruction for the agent chain")

        registry = build_workspace_registry(workspace_dir)
        executor = ToolExecutor(tool_registry=registry, workspace_dir=str(workspace_dir))
        prompt_builder = PromptBuilder(
            identity_store=ExperimentIdentityStore(),
            memory_system=None,
            tool_registry=registry,
            # prune_tools MUST stay False here: the production pruning allowlist is
            # hardcoded to builtin tool names and would strip read_file/write_file.
            prune_tools=False,
            memory_cfg={"recall_enabled": False},
        )
        loop = self.agentic_loop_cls(
            model_provider=self._model,
            tool_executor=executor,
            prompt_builder=prompt_builder,
            session_manager=HistorySession(self._history_messages(task_def, history)),
            memory_system=None,
        )

        calls_before = len(self._model.calls)
        try:
            result = run_sync(lambda: loop.run(instruction))
        except ModelCallLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - report as observable failure
            raise RuntimeError(f"agent chain failed: {type(exc).__name__}: {exc}") from exc

        call_slice = self._model.calls[calls_before:]
        first_error = next((c["error"] for c in call_slice if c["error"]), None)
        if first_error is not None and not any(c["tool_calls"] for c in call_slice):
            # No usable model output at all: never pretend this run worked.
            raise RuntimeError(f"model unavailable: {first_error}")

        tool_results = [self._normalize_tool_call(tc) for tc in
                        (getattr(result, "tool_calls_executed", None) or [])]
        chain_info = {
            "task_id": task_id,
            "runner_step": step,
            "chain_steps": int(getattr(result, "steps", 0) or 0),
            "model_calls": len(call_slice),
            "tool_calls": len(tool_results),
            "model_errors": [c["error"] for c in call_slice if c["error"]],
            "call_usage": [c["usage"] for c in call_slice],
            "final_text": str(getattr(result, "final_text", "") or "")[:2000],
        }
        self.last_chain = chain_info

        totals = {
            "input_tokens": sum(int(c["usage"].get("input_tokens", 0)) for c in call_slice),
            "output_tokens": sum(int(c["usage"].get("output_tokens", 0)) for c in call_slice),
            "api_calls": len(call_slice),
        }
        if not all("input_tokens" in c["usage"] and "output_tokens" in c["usage"] for c in call_slice):
            # Missing provider usage is unknown spend, not a zero-token response.
            # The kernel conservatively settles token caps while retaining call count.
            totals = {"api_calls": len(call_slice)}
        return {
            "action": {"name": "finish", "reason": "agent chain completed"},
            "usage": totals,
            "tool_results": tool_results,
            "chain": chain_info,
        }

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _normalize_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": str(tc.get("name") or ""),
            "arguments": tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {},
            "success": bool(tc.get("success")),
            "result": str(tc.get("result") or "")[:MAX_TOOL_RESULT_CHARS],
            "error_type": tc.get("error_type"),
            "error_message": tc.get("error_message"),
        }

    @staticmethod
    def _history_messages(task_def: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert kernel step history into chat turns for prompt context."""
        messages: list[dict[str, Any]] = []
        for item in history or []:
            action = item.get("action") or {}
            observation = item.get("observation") or {}
            if action:
                messages.append({
                    "role": "assistant",
                    "content": f"[tool call] {action.get('name')} {json.dumps(action.get('arguments') or {}, ensure_ascii=False)}",
                })
            if observation:
                messages.append({
                    "role": "user",
                    "content": f"[tool result] {json.dumps(observation, ensure_ascii=False)[:4000]}",
                })
        return messages


def run_sync(factory: Callable[[], Any]) -> Any:
    """Run an async chain from sync code, without nesting event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    # Already inside a loop (e.g. FastAPI): use a dedicated thread + loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


def environment_info() -> dict[str, Any]:
    """Frozen-environment provenance recorded with every live baseline run."""
    revision = "unknown"
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(KAGE_PROJECT_ROOT), capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            revision = proc.stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is best effort
        pass
    return {
        "kage_revision": revision,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


# ---------------------------------------------------------------------------
# Live provider construction (ModelBroker based; no silent fallback)
# ---------------------------------------------------------------------------
def build_live_provider(
    config: dict[str, Any] | None,
    *,
    role: str = "background",
    base_url: str | None = None,
    model_name: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    allow_hybrid: bool = False,
) -> tuple[ModelProvider, dict[str, Any]]:
    """Build the frozen provider for a live E0 run.

    Raises ``ProviderUnavailableError`` when the selected role cannot reach a
    real model (no credential, or HYBRID mode without explicit opt-in). Never
    returns a fake provider.
    """
    from core.model_broker import ModelBroker

    effective = json.loads(json.dumps(config or {}))  # deep copy without mutating caller
    model_cfg = effective.setdefault("model", {})
    cloud_cfg = model_cfg.setdefault("cloud_api", {})
    local_cfg = model_cfg.setdefault("local_runtime", {})
    broker_cfg = model_cfg.get("broker") or {}

    env_key = str(os.environ.get(api_key_env) or "").strip()
    if env_key and not str(cloud_cfg.get("api_key") or "").strip():
        cloud_cfg["api_key"] = env_key
    if base_url:
        cloud_cfg["base_url"] = base_url
        # The local profile rebuilds its URL from host/port, so translate the
        # override instead of setting a key ModelBroker ignores.
        try:
            from urllib.parse import urlparse

            parsed = urlparse(str(base_url))
            if parsed.hostname:
                local_cfg["host"] = parsed.hostname
            if parsed.port:
                local_cfg["port"] = parsed.port
        except Exception:  # noqa: BLE001 - fall back to configured values
            pass
    if model_name:
        cloud_cfg["model_name"] = model_name

    broker = ModelBroker(effective)
    profile = broker.profile(role)
    mode = profile.mode

    if mode == "hybrid" and not allow_hybrid:
        raise ProviderUnavailableError(
            f"role '{role}' resolves to HYBRID mode, which can silently escalate from "
            "the local model to the cloud mid-run. Re-run with --allow-hybrid-escalation "
            "to accept that (recorded in the report), or disable model.hybrid."
        )

    if mode == "cloud":
        key = str(cloud_cfg.get("api_key") or "").strip()
        if not key:
            raise ProviderUnavailableError(
                "live provider requires a cloud credential: set model.cloud_api.api_key "
                f"in the config or export {api_key_env}. Refusing to fall back to the "
                "fake provider."
            )
        provider = profile.provider
        info = {
            "role": role,
            "mode": mode,
            "model": str(cloud_cfg.get("model_name") or ""),
            "base_url": str(cloud_cfg.get("base_url") or ""),
            "provider_type": str(cloud_cfg.get("provider_type") or "openai"),
            "credential_source": (
                "config" if str((config or {}).get("model", {}).get("cloud_api", {}).get("api_key") or "").strip()
                else f"env:{api_key_env}"
            ),
        }
    else:
        provider = profile.provider
        info = {
            "role": role,
            "mode": mode,
            "model": str(local_cfg.get("model_name") or "local-model"),
            "base_url": f"http://{local_cfg.get('host') or '127.0.0.1'}:"
                        f"{int(local_cfg.get('port') or 8080)}/v1",
            "provider_type": "openai-compatible(local runtime)",
            "credential_source": "local-runtime",
        }

    if str((broker_cfg or {}).get(role + "_provider") or "").strip().lower() == "cloud" and mode == "local":
        # Defensive: an explicit cloud role with no credential silently degrades to
        # local inside ModelBroker. E0 must not hide that.
        raise ProviderUnavailableError(
            f"role '{role}' is configured as cloud but no credential is present; "
            "ModelBroker would silently use the local runtime. Refusing."
        )
    return provider, info

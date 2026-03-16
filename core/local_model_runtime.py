from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


ManagedModelGetter = Callable[[str], dict | None]


@dataclass
class RuntimeStartResult:
    ok: bool
    payload: dict[str, Any]


class LocalModelRuntime:
    """Manage a local llama.cpp-compatible inference server process.

    This runtime intentionally owns only process lifecycle and command
    construction. API handlers remain responsible for HTTP semantics.
    """

    def __init__(
        self,
        user_dir: str,
        managed_model_getter: ManagedModelGetter,
        which: Callable[[str], str | None] | None = None,
        path_exists: Callable[[str], bool] | None = None,
        popen_factory: Callable[..., subprocess.Popen] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.user_dir = str(user_dir)
        self._get_managed_model = managed_model_getter
        self._which = which or shutil.which
        self._path_exists = path_exists or os.path.exists
        self._popen_factory = popen_factory or subprocess.Popen
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._log_handle = None
        self._state: dict[str, Any] = {
            "status": "stopped",  # stopped|starting|running|error
            "pid": None,
            "host": "127.0.0.1",
            "port": 8080,
            "model_id": None,
            "model_path": None,
            "started_at": None,
            "updated_at": self._clock(),
            "error": None,
            "cmd": None,
            "log_path": os.path.join(self.user_dir, "llama-server.log"),
        }

    def is_running(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state)
            st["running"] = self.is_running()
            if st["status"] == "running" and not st["running"]:
                st["status"] = "stopped"
            return st

    def find_binary(self, explicit: str | None = None) -> str | None:
        if explicit:
            path = str(explicit).strip()
            if path and self._path_exists(path) and os.access(path, os.X_OK):
                return path
        return self._which("llama-server")

    def resolve_model(self, payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
        model_id = str(payload.get("model_id") or "").strip() or None
        model_path = str(payload.get("model_path") or "").strip() or None
        if model_id:
            entry = self._get_managed_model(model_id)
            if not entry:
                return (None, None, "model_id not found")
            path = str(entry.get("path") or "").strip()
            if not path:
                return (None, None, "model has no path")
            return (model_id, path, None)
        if model_path:
            if not self._path_exists(model_path):
                return (None, None, "model_path not found")
            return (None, model_path, None)
        return (None, None, "model_id or model_path required")

    def build_command(self, llama_bin: str, model_path: str, payload: dict[str, Any]) -> list[str]:
        host = str(payload.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        port = int(payload.get("port") or 8080)
        ctx = int(payload.get("ctx") or 8192)
        max_tokens = int(payload.get("max_tokens") or 1024)
        temp = float(payload.get("temp") or 0.7)
        top_p = float(payload.get("top_p") or 0.8)
        top_k = int(payload.get("top_k") or 20)
        min_p = float(payload.get("min_p") or 0)
        presence_penalty = float(payload.get("presence_penalty") or 1.5)
        ngl = int(payload.get("ngl") or 99)
        reasoning = str(payload.get("reasoning") or "off").strip().lower() or "off"
        return [
            llama_bin,
            "-m",
            str(model_path),
            "--jinja",
            "--host",
            host,
            "--port",
            str(port),
            "-ngl",
            str(ngl),
            "--flash-attn",
            "auto",
            "-c",
            str(ctx),
            "-n",
            str(max_tokens),
            "--temp",
            str(temp),
            "--top-p",
            str(top_p),
            "--top-k",
            str(top_k),
            "--min-p",
            str(min_p),
            "--presence-penalty",
            str(presence_penalty),
            "--no-context-shift",
            "--reasoning",
            reasoning,
        ]

    def start(self, payload: dict[str, Any]) -> RuntimeStartResult:
        host = str(payload.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        port = int(payload.get("port") or 8080)
        force_restart = bool(payload.get("force_restart") or False)

        model_id, model_path, err = self.resolve_model(payload)
        if err:
            return RuntimeStartResult(False, {"error": err})

        llama_bin = self.find_binary(payload.get("binary_path"))
        if not llama_bin:
            return RuntimeStartResult(
                False,
                {"error": "llama-server not found in PATH (install llama.cpp or provide binary_path)"},
            )

        with self._lock:
            if self.is_running():
                same_target = (
                    str(self._state.get("model_path") or "").strip() == str(model_path or "").strip()
                    and int(self._state.get("port") or 0) == port
                    and str(self._state.get("host") or "") == host
                )
                if not force_restart and same_target:
                    return RuntimeStartResult(True, dict(self._state))
                if not force_restart:
                    return RuntimeStartResult(False, {"error": "llama-server already running (use force_restart=true)"})

            self._stop_locked()

            os.makedirs(self.user_dir, exist_ok=True)
            log_path = str(self._state.get("log_path") or os.path.join(self.user_dir, "llama-server.log"))
            cmd = self.build_command(llama_bin, str(model_path), payload)

            self._state.update(
                {
                    "status": "starting",
                    "error": None,
                    "host": host,
                    "port": port,
                    "model_id": model_id,
                    "model_path": model_path,
                    "cmd": cmd,
                    "updated_at": self._clock(),
                }
            )

            try:
                self._log_handle = open(log_path, "a", encoding="utf-8")
                self._proc = self._popen_factory(
                    cmd,
                    stdout=self._log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self._state.update(
                    {
                        "status": "running",
                        "pid": self._proc.pid,
                        "started_at": self._clock(),
                        "updated_at": self._clock(),
                        "log_path": log_path,
                    }
                )
                return RuntimeStartResult(True, dict(self._state))
            except Exception as exc:
                self._state.update(
                    {
                        "status": "error",
                        "error": str(exc),
                        "updated_at": self._clock(),
                    }
                )
                self._close_log_handle()
                self._proc = None
                return RuntimeStartResult(False, dict(self._state))

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_locked()
            return dict(self._state)

    def _stop_locked(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._proc = None
            self._close_log_handle()
            self._state.update({"status": "stopped", "pid": None, "updated_at": self._clock()})
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None
        self._close_log_handle()
        self._state.update({"status": "stopped", "pid": None, "updated_at": self._clock()})

    def _close_log_handle(self) -> None:
        handle = self._log_handle
        self._log_handle = None
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass

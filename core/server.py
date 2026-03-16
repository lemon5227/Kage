# pyright: reportGeneralTypeIssues=false
import asyncio
import json
import traceback
import random
import time
import re
import threading
import subprocess
import hashlib
import signal
import sys
import datetime
import os
import contextlib
from urllib.parse import quote
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
import shutil
import uvicorn
from uuid import uuid4
from typing import Any
from core.audio_orchestrator import AudioOrchestrator
from core.background_lane import BackgroundLane
from core.background_worker import BackgroundWorker
from core.dialog_state_machine import DialogStateMachine
from core.interaction_state import (
    PendingVideoFollowup,
    make_pending_chat_followup,
    make_pending_confirm_inferred_command,
    make_pending_confirm_tool,
    make_pending_video_followup,
    pending_requires_thinking,
)
from core.job_store import InMemoryJobStore
from core.local_model_runtime import LocalModelRuntime
from core.model_broker import ModelBroker
from core.pending_handlers import (
    handle_pending_action,
)
from core.response_sanitizer import sanitize_for_speech_text, strip_reasoning_artifacts
from core.realtime_handlers import (
    extract_video_subject,
    format_video_evidence,
    is_video_intent,
    normalize_video_query_for_search,
    preprocess_video_followup_turn,
    undo_fastpath,
    video_selection_evidence,
    video_subject_match_score,
    wants_open_video_action,
    weather_fastpath,
)
from core.realtime_lane import (
    classify_realtime_task,
    decide_realtime_command,
    describe_command_intent,
    extract_correction_text,
    is_cancel_text,
    is_confirm_text,
)
from core.trace import log


def _env_truthy(name: str) -> bool:
    v = str(os.environ.get(name, "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def _enable_timestamped_stdio() -> None:
    """Prefix each stdout/stderr line with a timestamp.

    This is useful for interactive debugging and performance tracing.
    Enable with `KAGE_LOG_TS=1`.
    """

    class _TSWriter:
        def __init__(self, underlying):
            self._u = underlying
            self._at_line_start = True

        def write(self, s):
            try:
                text = str(s)
            except Exception:
                text = ""
            if not text:
                return 0

            out = []
            for part in text.splitlines(True):
                if self._at_line_start and part not in ("\n", "\r\n"):
                    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    out.append(f"[{ts}] ")
                out.append(part)
                self._at_line_start = part.endswith("\n")
            return self._u.write("".join(out))

        def flush(self):
            return self._u.flush()

        def isatty(self):
            try:
                return self._u.isatty()
            except Exception:
                return False

    # Avoid double-wrapping
    if not isinstance(sys.stdout, _TSWriter):
        sys.stdout = _TSWriter(sys.stdout)
    if not isinstance(sys.stderr, _TSWriter):
        sys.stderr = _TSWriter(sys.stderr)


if _env_truthy("KAGE_LOG_TS"):
    _enable_timestamped_stdio()

from core.intent_router import is_undo_request

# Import Kage Core Components
# Assuming this file is core/server.py, we need to adjust paths if necessary
# But since we run from root usually, we rely on sys.path or relative imports if in package.
# We will setup sys.path in __main__ execution or assume module usage.
import sys
import os

# Ensure we can import from the same directory or parent
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

 

from contextlib import asynccontextmanager

# Global Instance (Lazy Load)
kage_server = None
_main_loop: asyncio.AbstractEventLoop | None = None
_runtime_lock = threading.Lock()
_runtime_state: dict[str, Any] = {
    "status": "idle",  # idle|booting|ready|error
    "stage": "idle",
    "started_at": None,
    "error": None,
    "updated_at": time.time(),
}


def _get_user_dir() -> str:
    return os.path.expanduser("~/.kage")


def _get_user_config_path() -> str:
    return os.path.join(_get_user_dir(), "config.json")


def _get_models_dir() -> str:
    return os.path.join(_get_user_dir(), "models")


def _get_models_manifest_path() -> str:
    return os.path.join(_get_models_dir(), "manifest.json")


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_models_manifest() -> dict:
    """Return manifest dict: {"models": {<id>: {...}}}."""
    path = _get_models_manifest_path()
    data = _load_json(path)
    if not isinstance(data, dict):
        return {"models": {}}
    models = data.get("models")
    if not isinstance(models, dict):
        data["models"] = {}
    return data


def _save_models_manifest(data: dict) -> None:
    _save_json(_get_models_manifest_path(), data)


def _make_model_id(repo_id: str, filename: str | None = None, revision: str | None = None) -> str:
    base = "|".join(
        [
            str(repo_id or "").strip(),
            str(filename or "").strip(),
            str(revision or "").strip(),
        ]
    )
    digest = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    safe_repo = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(repo_id or "model")).strip("-")
    return f"{safe_repo}-{digest}".lower()


def _guess_qwen3_gguf_filename(repo_id: str, variant: str) -> str | None:
    """Best-effort mapping from repo_id + variant to a gguf filename for Qwen3 official repos."""
    rid = str(repo_id or "")
    v = str(variant or "").strip()
    if not rid or not v:
        return None
    if not rid.startswith("Qwen/") or not rid.endswith("-GGUF"):
        return None
    # Official Qwen GGUF repos use filenames like: Qwen3-4B-Q4_K_M.gguf
    name = rid.split("/", 1)[1]
    m = re.match(r"^Qwen3-(\d+(?:\.\d+)?)(B)-GGUF$", name)
    if not m:
        return None
    size = m.group(1)
    v_norm = v.upper()
    return f"Qwen3-{size}B-{v_norm}.gguf"


def _register_managed_model(entry: dict) -> dict:
    manifest = _load_models_manifest()
    models = manifest.setdefault("models", {})
    mid = str(entry.get("id") or "").strip()
    if not mid:
        raise ValueError("model id required")
    models[mid] = dict(entry)
    _save_models_manifest(manifest)
    return dict(models[mid])


def _list_managed_models() -> list[dict]:
    manifest = _load_models_manifest()
    models = manifest.get("models")
    if not isinstance(models, dict):
        return []
    out = []
    for _, v in models.items():
        if isinstance(v, dict):
            out.append(dict(v))
    out.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return out


def _get_managed_model(model_id: str) -> dict | None:
    mid = str(model_id or "").strip()
    if not mid:
        return None
    manifest = _load_models_manifest()
    models = manifest.get("models")
    if not isinstance(models, dict):
        return None
    v = models.get(mid)
    return dict(v) if isinstance(v, dict) else None


def _delete_managed_model(model_id: str) -> dict:
    mid = str(model_id or "").strip()
    if not mid:
        return {"status": "error", "message": "model_id required"}
    manifest = _load_models_manifest()
    models = manifest.get("models")
    if not isinstance(models, dict) or mid not in models:
        return {"status": "error", "message": "model not found"}
    entry = models.get(mid) if isinstance(models.get(mid), dict) else {}
    path = str((entry or {}).get("path") or "").strip()
    # Remove manifest first to avoid partial state if deletion fails.
    try:
        del models[mid]
        manifest["models"] = models
        _save_models_manifest(manifest)
    except Exception:
        pass
    # Delete on-disk model directory/file.
    try:
        if path and os.path.exists(path):
            # If path points to a file inside a model directory, delete the directory.
            target = path
            if os.path.isfile(target):
                target = os.path.dirname(target)
            if os.path.isdir(target) and os.path.realpath(target).startswith(os.path.realpath(_get_models_dir())):
                shutil.rmtree(target)
            elif os.path.isfile(path) and os.path.realpath(path).startswith(os.path.realpath(_get_models_dir())):
                os.remove(path)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "success", "message": f"Deleted {mid}"}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _with_config_defaults(cfg: dict) -> dict:
    out = dict(cfg) if isinstance(cfg, dict) else {}
    model_cfg = dict(out.get("model") or {})
    local_runtime = dict(model_cfg.get("local_runtime") or {})
    local_runtime_defaults = {
        "engine": "llama.cpp",
        "host": "127.0.0.1",
        "port": 8080,
        "ctx": 8192,
        "max_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "ngl": 99,
        "reasoning": "off",
        "timeout_sec": 120,
    }
    local_runtime = _deep_merge(local_runtime_defaults, local_runtime)
    broker_cfg = dict(model_cfg.get("broker") or {})
    broker_defaults = {
        "routing_provider": "local",
        "realtime_provider": "local",
        "background_provider": "local",
        "fallback_provider": "cloud",
    }
    broker_cfg = _deep_merge(broker_defaults, broker_cfg)
    local_profiles = model_cfg.get("local_profiles")
    if not isinstance(local_profiles, list) or not local_profiles:
        local_profiles = [
            {
                "id": "qwen3-4b-fast",
                "label": "Qwen3 4B",
                "model": "Qwen/Qwen3-4B-GGUF",
                "description": "Fast local baseline for realtime tasks",
            },
            {
                "id": "qwen3-8b-balanced",
                "label": "Qwen3 8B",
                "model": "Qwen/Qwen3-8B-GGUF",
                "description": "Stronger local model for heavier tasks",
            },
        ]
    model_cfg["local_runtime"] = local_runtime
    model_cfg["broker"] = broker_cfg
    model_cfg["local_profiles"] = local_profiles
    out["model"] = model_cfg
    return out


def _load_effective_config() -> dict:
    repo_cfg = _load_json(os.path.join(parent_dir, "config", "settings.json"))
    user_cfg = _load_json(_get_user_config_path())
    return _with_config_defaults(_deep_merge(repo_cfg, user_cfg))


def _save_user_config_patch(patch: dict) -> dict:
    path = _get_user_config_path()
    current = _load_json(path)
    merged = _deep_merge(current, patch)
    _save_json(path, merged)
    return merged

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load Models (ONLY in Main Process)
    global kage_server
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    mode = os.environ.get("KAGE_MODE", "runtime").strip().lower()
    if mode == "control":
        print("🚦 Lifespan Startup: control mode (skip heavy init)")
    else:
        if kage_server is None:
            print("🚦 Lifespan Startup: initializing KageServer...")
            kage_server = KageServer(config=_load_effective_config())
        # Optionally auto-start the main loop (mic / wakeword) even without a
        # websocket client connected.
        autostart_env = str(os.environ.get("KAGE_AUTOSTART", "")).strip().lower()
        always_listen_env = str(os.environ.get("KAGE_ALWAYS_LISTEN", "")).strip().lower()
        if autostart_env in ("1", "true", "yes", "on") or always_listen_env in ("1", "true", "yes", "on"):
            try:
                kage_server.ensure_main_loop_started()
                print("🚀 Main loop autostart enabled")
            except Exception as e:
                print(f"⚠️ Failed to autostart main loop: {e}")
    yield
    # Shutdown
    if kage_server:
        kage_server.is_running = False
        try:
            await kage_server.background_worker.stop()
        except Exception:
            pass
        print("🛑 Lifespan Shutdown: stopping KageServer...")

app = FastAPI(lifespan=lifespan)


# --- Model Download Jobs (Control Plane) ---
_download_jobs = InMemoryJobStore()


def _find_active_download_job(repo_id: str, revision: str | None = None, filename: str | None = None) -> str | None:
    """Return an existing job_id if the same repo/file is already downloading."""
    match = _download_jobs.find_first(
        lambda job: (
            job.get("repo_id") == repo_id
            and (filename is None or str(job.get("filename") or "").strip() == str(filename or "").strip())
            and (revision is None or job.get("revision") in (None, revision))
            and job.get("status") in ("queued", "running")
        )
    )
    return str(match.get("job_id")) if isinstance(match, dict) else None


def _set_job(job_id: str, patch: dict):
    _download_jobs.update(job_id, patch)


def _get_job(job_id: str) -> dict | None:
    return _download_jobs.get(job_id)


def _list_jobs() -> list[dict]:
    return _download_jobs.list()


@app.get("/api/health")
async def health():
    mode = os.environ.get("KAGE_MODE", "runtime").strip().lower()
    return {
        "ok": True,
        "mode": mode,
        "runtime_started": kage_server is not None,
    }


@app.get("/api/config")
async def get_config():
    return _load_effective_config()


@app.post("/api/config")
async def set_config(payload: dict):
    if not isinstance(payload, dict):
        return {"error": "invalid payload"}
    saved = _save_user_config_patch(payload)
    return {"status": "ok", "saved": saved}


@app.get("/api/runtime/status")
async def runtime_status():
    with _runtime_lock:
        return dict(_runtime_state)


@app.post("/api/runtime/start")
async def runtime_start():
    global kage_server

    with _runtime_lock:
        if kage_server is not None:
            _runtime_state.update({
                "status": "ready",
                "stage": "ready",
                "error": None,
                "updated_at": time.time(),
            })
            return dict(_runtime_state)
        if _runtime_state.get("status") == "booting":
            return dict(_runtime_state)
        _runtime_state.update({
            "status": "booting",
            "stage": "starting",
            "started_at": time.time(),
            "error": None,
            "updated_at": time.time(),
        })

    def _boot():
        global kage_server
        try:
            print("🚀 Runtime boot requested")
            with _runtime_lock:
                _runtime_state.update({"stage": "loading_config", "updated_at": time.time()})
            cfg = _load_effective_config()
            with _runtime_lock:
                _runtime_state.update({"stage": "initializing_runtime", "updated_at": time.time()})

            kage_server = KageServer(config=cfg)
            print("✅ Runtime initialized")

            if _main_loop is not None:
                with _runtime_lock:
                    _runtime_state.update({"stage": "starting_main_loop", "updated_at": time.time()})

                def _start_loop_and_mark_ready():
                    try:
                        if kage_server is None:
                            raise RuntimeError("runtime not initialized")
                        kage_server.ensure_main_loop_started()
                        with _runtime_lock:
                            _runtime_state.update({
                                "status": "ready",
                                "stage": "ready",
                                "error": None,
                                "updated_at": time.time(),
                            })
                        print("✅ Runtime ready")
                    except Exception as e:
                        with _runtime_lock:
                            _runtime_state.update({
                                "status": "error",
                                "stage": "error",
                                "error": str(e),
                                "updated_at": time.time(),
                            })
                        print(f"❌ Runtime loop start failed: {e}")

                _main_loop.call_soon_threadsafe(_start_loop_and_mark_ready)
            else:
                with _runtime_lock:
                    _runtime_state.update({
                        "status": "ready",
                        "stage": "ready",
                        "error": None,
                        "updated_at": time.time(),
                    })
                print("✅ Runtime ready")
        except Exception as e:
            print(f"❌ Runtime boot failed: {e}")
            with _runtime_lock:
                _runtime_state.update({
                    "status": "error",
                    "stage": "error",
                    "error": str(e),
                    "updated_at": time.time(),
                })

    threading.Thread(target=_boot, daemon=True).start()
    return dict(_runtime_state)


@app.get("/api/models/download")
async def list_model_downloads():
    return _list_jobs()


@app.get("/api/models/download/{job_id}")
async def get_model_download(job_id: str):
    job = _get_job(job_id)
    if not job:
        return {"error": "job not found"}
    return job


@app.post("/api/models/download")
async def start_model_download(payload: dict):
    repo_id = str(payload.get("repo_id") or "").strip()
    revision = payload.get("revision")
    filename = str(payload.get("filename") or "").strip() or None
    variant = str(payload.get("variant") or "").strip() or None
    if not repo_id:
        return {"error": "repo_id required"}

    if not filename and variant:
        filename = _guess_qwen3_gguf_filename(repo_id, variant)
    if not filename:
        return {"error": "filename required (or provide variant for known repos)"}
    if not str(filename).lower().endswith(".gguf"):
        return {"error": "only .gguf downloads are supported by this endpoint"}

    # Normalize known Qwen GGUF filenames when user sends old naming.
    # Example: qwen3-4b-q4_k_m.gguf -> Qwen3-4B-Q4_K_M.gguf
    m = re.match(r"^qwen3-(\d+(?:\.\d+)?)b-(q\d+_[a-z0-9_]+)\.gguf$", str(filename).strip(), flags=re.IGNORECASE)
    if m and repo_id.startswith("Qwen/") and repo_id.endswith("-GGUF"):
        size = m.group(1)
        variant_guess = m.group(2).upper()
        filename = f"Qwen3-{size}B-{variant_guess}.gguf"

    target_dir = str(payload.get("target_dir") or "").strip() or _get_models_dir()
    os.makedirs(target_dir, exist_ok=True)

    # De-dupe: if the same repo is already downloading, return that job.
    existing = _find_active_download_job(repo_id, revision=revision if isinstance(revision, str) else None, filename=filename)
    if existing:
        return {"job_id": existing, "status": "already_running"}

    job_id = uuid4().hex
    now = time.time()
    _download_jobs.create(
        job_id,
        {
            "repo_id": repo_id,
            "revision": revision,
            "filename": filename,
            "variant": variant,
            "target_dir": target_dir,
            "status": "queued",
            "stage": "queued",
            "created_at": now,
            "updated_at": now,
            "current_file": None,
            "file_downloaded": 0,
            "file_total": None,
            "error": None,
            "model_id": None,
            "local_path": None,
        },
    )

    def _run():
        try:
            from huggingface_hub import hf_hub_download
            from tqdm.auto import tqdm

            class _JobTqdm(tqdm):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    _set_job(job_id, {"status": "running", "stage": "downloading", "updated_at": time.time()})

                def set_description_str(self, desc=None, refresh=True):
                    if desc:
                        _set_job(job_id, {"current_file": str(desc), "updated_at": time.time()})
                    return super().set_description_str(desc=desc, refresh=refresh)

                def update(self, n=1):
                    try:
                        cur = int(getattr(self, "n", 0) or 0)
                        _set_job(
                            job_id,
                            {
                                "file_downloaded": cur,
                                "file_total": int(self.total) if self.total is not None else None,
                                "updated_at": time.time(),
                            },
                        )
                    except Exception:
                        pass
                    return super().update(n)

            # Download a single GGUF file so the frontend can manage variants deterministically.
            model_id = _make_model_id(repo_id, filename=filename, revision=revision if isinstance(revision, str) else None)
            local_dir = os.path.join(target_dir, model_id)
            os.makedirs(local_dir, exist_ok=True)

            local_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                revision=revision,
                local_dir=local_dir,
                tqdm_class=_JobTqdm,
            )
            size_bytes = None
            if os.path.exists(local_path) and os.path.isfile(local_path):
                try:
                    size_bytes = os.path.getsize(local_path)
                except Exception:
                    size_bytes = None

            entry = {
                "id": model_id,
                "repo_id": repo_id,
                "revision": revision if isinstance(revision, str) else None,
                "filename": filename,
                "variant": variant,
                "format": "gguf",
                "engine": "llama.cpp",
                "path": local_path,
                "size_bytes": size_bytes,
                "created_at": time.time(),
            }
            try:
                _register_managed_model(entry)
            except Exception:
                pass

            _set_job(
                job_id,
                {
                    "status": "completed",
                    "stage": "completed",
                    "updated_at": time.time(),
                    "model_id": model_id,
                    "local_path": local_path,
                },
            )
        except Exception as e:
            _set_job(job_id, {"status": "failed", "stage": "failed", "error": str(e), "updated_at": time.time()})

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/models")
async def list_models():
    """List managed models (preferred) and legacy HF cache models."""

    def _scan_hf_cache_models():
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        if not os.path.exists(cache_dir):
            return []

        models = []
        try:
            for item in os.listdir(cache_dir):
                if not item.startswith("models--"):
                    continue
                path = os.path.join(cache_dir, item)
                if not os.path.isdir(path):
                    continue

                size_bytes = 0
                for root, _, files in os.walk(path):
                    for f in files:
                        try:
                            size_bytes += os.path.getsize(os.path.join(root, f))
                        except Exception:
                            pass

                parts = item.split("--")
                readable_name = item
                if len(parts) >= 3:
                    author = parts[1]
                    repo = "-".join(parts[2:])
                    readable_name = f"{author}/{repo}"

                models.append(
                    {
                        "id": item,
                        "name": readable_name,
                        "size_bytes": size_bytes,
                    }
                )
        except Exception as e:
            print(f"Error listing models: {e}")

        return models

    managed = await asyncio.to_thread(_list_managed_models)
    hf_cache = await asyncio.to_thread(_scan_hf_cache_models)
    return {"managed": managed, "hf_cache": hf_cache}

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    """Delete a model from cache"""
    mid = str(model_id or "").strip()
    if not mid:
        return {"error": "Invalid model ID"}

    # Managed model deletion
    if not mid.startswith("models--"):
        return await asyncio.to_thread(_delete_managed_model, mid)

    # Legacy HF cache deletion (kept for backward compatibility)
    if ".." in mid or "/" in mid:
        return {"error": "Invalid model ID"}

    def _do_delete_hf_cache():
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        target_path = os.path.join(cache_dir, mid)

        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
                return {"status": "success", "message": f"Deleted {mid}"}
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Model not found"}

    return await asyncio.to_thread(_do_delete_hf_cache)


_local_runtime = LocalModelRuntime(
    user_dir=_get_user_dir(),
    managed_model_getter=_get_managed_model,
)


@app.get("/api/models/llama/status")
async def llama_status():
    return _local_runtime.status()


@app.post("/api/models/llama/start")
async def llama_start(payload: dict):
    req = payload if isinstance(payload, dict) else {}
    cfg = _load_effective_config()
    runtime_cfg = (
        cfg.get("model", {}).get("local_runtime", {})
        if isinstance(cfg.get("model", {}).get("local_runtime", {}), dict)
        else {}
    )
    merged = _deep_merge(runtime_cfg, req)
    result = _local_runtime.start(merged)
    return result.payload


@app.post("/api/models/llama/stop")
async def llama_stop():
    return _local_runtime.stop()


@app.post("/api/models/activate")
async def activate_model(payload: dict):
    """Activate a model provider by writing a user config patch."""
    provider = str(payload.get("provider") or "").strip() or "llama.cpp"
    if provider not in ("llama.cpp", "openai"):
        return {"error": "unsupported provider"}

    base_url = str(payload.get("base_url") or "").strip()
    model_name = str(payload.get("model_name") or "").strip() or "local-model"
    api_key = str(payload.get("api_key") or "").strip() or "local"

    if not base_url:
        # Default to current llama-server status
        st = _local_runtime.status()
        if not st.get("running"):
            return {"error": "base_url not provided and llama-server not running"}
        base_url = f"http://{st.get('host') or '127.0.0.1'}:{st.get('port') or 8080}/v1"

    timeout_sec = int(payload.get("timeout_sec") or 120)
    patch = {
        "model": {
            "preferred_model": "openai",
            "cloud_api": {
                "base_url": base_url,
                "api_key": api_key,
                "model_name": model_name,
                "timeout_sec": timeout_sec,
            },
        }
    }
    saved = _save_user_config_patch(patch)
    return {"status": "ok", "saved": saved}

class KageServer:
    def __init__(self, config: dict | None = None):
        print("⚙️ Initializing Kage Server (Heavy Load)...")

        # Lazy imports to keep Control Plane startup fast
        from core.memory import MemorySystem
        from core.mouth import KageMouth
        from core.ears import KageEars
        from core.tool_registry import create_default_registry

        # New modules
        from core.identity_store import IdentityStore
        from core.session_manager import SessionManager
        from core.tool_executor import ToolExecutor
        from core.prompt_builder import PromptBuilder
        from core.agentic_loop import AgenticLoop
        from core.heartbeat import Heartbeat

        cfg = config or {}
        model_path = (
            cfg.get("model", {}).get("path")
            or cfg.get("model", {}).get("default_model")
            or "Qwen/Qwen3-4B-GGUF"
        )
        voice = cfg.get("voice", {}).get("tts_voice") or "zh-CN-XiaoyiNeural"
        self._wakeword_enabled_cfg = bool(cfg.get("wakeword", {}).get("enabled", True))
        self._text_only_mode = _env_truthy("KAGE_TEXT_ONLY") or _env_truthy("KAGE_BENCH_TEXT_ONLY")
        self._weather_fastpath_enabled = not (str(os.environ.get("KAGE_FASTPATH_WEATHER", "1")).strip().lower() in ("0", "false", "no", "off"))
        self._route_model_assist_enabled = _env_truthy("KAGE_ROUTE_MODEL_ASSIST")
        # Runtime override for quick testing without editing config files.
        # If enabled, skip wake word and enter always-listen mode.
        always_listen_env = str(os.environ.get("KAGE_ALWAYS_LISTEN", "")).strip().lower()
        wakeword_env = str(os.environ.get("KAGE_WAKEWORD", "")).strip().lower()
        if always_listen_env in ("1", "true", "yes", "on"):
            self._wakeword_enabled_cfg = False
        elif wakeword_env in ("0", "false", "no", "off"):
            self._wakeword_enabled_cfg = False

        # --- Identity Store ---
        print("🪪 Loading identity store...", flush=True)
        self.identity_store = IdentityStore()
        self.identity_store.ensure_files_exist()

        print("🧠 Loading memory...", flush=True)
        self.memory = MemorySystem()

        # --- Session persistence ---
        print("📝 Loading session manager...", flush=True)
        self.session_manager = SessionManager()
        self.session_manager.load_from_file()

        model_cfg = cfg.get("model", {})
        cloud_cfg = model_cfg.get("cloud_api", {}) if isinstance(model_cfg.get("cloud_api", {}), dict) else {}
        self.model_broker = ModelBroker(cfg)
        realtime_profile = self.model_broker.profile("realtime")
        background_profile = self.model_broker.profile("background")

        print(
            f"🧠 Realtime model provider: {realtime_profile.mode} ({realtime_profile.name})",
            flush=True,
        )
        print(
            f"🧠 Background model provider: {background_profile.mode} ({background_profile.name})",
            flush=True,
        )

        if self._text_only_mode:
            print("🧪 Text-only mode enabled: skip TTS/ASR init", flush=True)
            self.mouth = None
            self.ears = None
        else:
            print(f"🗣️ Initializing TTS voice: {voice}", flush=True)
            self.mouth = KageMouth(voice=voice)

            print("🎧 Loading ASR models...", flush=True)
            self.ears = KageEars(model_id="paraformer-zh")

        # --- Tool Registry ---
        print("🧰 Loading tool registry...", flush=True)
        self.tool_registry = create_default_registry(memory_system=self.memory)
        # NOTE: Runtime uses unified ToolRegistry + ToolExecutor + AgenticLoop.
        # Keep runtime tool surface small and deterministic.
        self.tools = None

        # --- Tool Executor (使用新的 Tool_Registry) ---
        self.tool_executor = ToolExecutor(tool_registry=self.tool_registry)

        # --- Model Providers by role ---
        self.routing_model_provider = self.model_broker.routing_provider
        self.realtime_model_provider = self.model_broker.realtime_provider
        self.model_provider = self.model_broker.background_provider
        self.fallback_model_provider = self.model_broker.fallback_provider

        # --- Prompt Builder (使用新的 Tool_Registry) ---
        self.prompt_builder = PromptBuilder(
            identity_store=self.identity_store,
            memory_system=self.memory,
            tool_registry=self.tool_registry,
            memory_cfg=cfg.get("memory", {}) if isinstance(cfg.get("memory", {}), dict) else {},
            prune_tools=True,
        )

        # --- Agentic Loop ---
        self.agentic_loop = AgenticLoop(
            model_provider=self.model_provider,
            tool_executor=self.tool_executor,
            prompt_builder=self.prompt_builder,
            session_manager=self.session_manager,
        )

        # --- Heartbeat ---
        heartbeat_cfg = cfg.get("heartbeat", {})
        heartbeat_interval = heartbeat_cfg.get("interval_minutes", 30)
        heartbeat_enabled = heartbeat_cfg.get("enabled", True)
        self.heartbeat = Heartbeat(
            tool_executor=self.tool_executor,
            session_manager=self.session_manager,
            interval_minutes=heartbeat_interval,
        )
        self._heartbeat_enabled = heartbeat_enabled

        # Short-lived interactive dialog state.
        from core.session_state import SessionState
        self.session = SessionState()
        self.dialog_state = DialogStateMachine(self.session)
        self.background_lane = BackgroundLane()
        self.audio_orchestrator = AudioOrchestrator(
            wakeword_enabled_cfg=self._wakeword_enabled_cfg,
        )
        self.background_worker = BackgroundWorker(
            lane=self.background_lane,
            processor=self._process_background_job,
            on_event=self._notify_job_event,
        )
        
        self.active_websocket: WebSocket | None = None
        self.is_running = True
        self._main_loop_task: asyncio.Task | None = None
        self._ui_state = "IDLE"
        self._speech_revision = 0
        self.motion_groups = {
            "Idle": 3,
            "Tap": 2,
        }
        self.motion_group_weights = {
            "Idle": 1,
            "Tap": 3,
        }
        self.motion_emotion_weights = {
            "happy": {"Idle": 1, "Tap": 5},
            "surprised": {"Idle": 1, "Tap": 4},
            "sad": {"Idle": 4, "Tap": 1},
            "angry": {"Idle": 2, "Tap": 3},
        }
        self.motion_cooldown_sec = 4.0
        self.motion_cooldown_min_sec = 2.5
        self.motion_cooldown_max_sec = 6.0
        self._last_motion_time = 0.0
        self.expression_duration_base_sec = 2.5
        self.expression_duration_per_char = 0.04
        self.expression_duration_min_sec = 2.0
        self.expression_duration_max_sec = 6.0
        self.expression_map = {
            "neutral": "f05",
            "happy": {
                "choices": ["f00", "f01"],
                "weights": [3, 1],
            },
            "sad": "f03",
            "angry": "f07",
            "fear": "f06",
            "surprised": "f02",
        }
        self._fast_cache = {}
        self._text_input_queue: asyncio.Queue = asyncio.Queue()
        self._active_turn_id: str | None = None
        threading.Thread(target=self._prefetch_local_city, daemon=True).start()
        print("✅ Kage Server Ready!")

    # ... (Rest of KageServer methods - same as before) ...
    async def connect(self, websocket: WebSocket):
        if self.active_websocket and self.active_websocket is not websocket:
            try:
                await self.active_websocket.close()
            except Exception:
                pass
        if websocket.application_state != WebSocketState.CONNECTED:
            await websocket.accept()
        self.active_websocket = websocket
        # Reset per-connection interactive pending state to avoid leaking
        # multi-turn confirmation context across clients/bench cases.
        try:
            self.dialog_state.clear_pending()
        except Exception:
            pass
        print("🔌 Client connected!")
        await self.send_state("IDLE")

    async def disconnect(self):
        self.active_websocket = None
        print("🔌 Client disconnected")

    def ensure_main_loop_started(self):
        """Start the main loop once; keep it running across reconnects."""
        self.background_worker.ensure_started()
        if self._main_loop_task is not None and not self._main_loop_task.done():
            return
        self._main_loop_task = asyncio.create_task(self.run_loop())

    async def send_message(self, type_: str, data: dict):
        if self.active_websocket:
            try:
                payload = {"type": type_, **data}
                if self._active_turn_id and type_ in ("speech", "transcription", "state", "expression", "motion"):
                    payload["turn_id"] = str(self._active_turn_id)
                await self.active_websocket.send_json(payload)
            except Exception as e:
                print(f"Send Error: {e}")

    def _state_payload(self, state: str) -> dict[str, str]:
        snapshot = self.dialog_state.snapshot()
        return {
            "state": str(state or ""),
            "dialog_phase": snapshot.phase,
            "pending_kind": snapshot.pending_kind,
        }

    def _dialog_trace_fields(self) -> dict[str, str]:
        snapshot = self.dialog_state.snapshot()
        return {
            "dialog_phase": snapshot.phase,
            "pending_kind": snapshot.pending_kind,
        }

    def _job_event_payload(self, event: str, job: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "event": str(event or ""),
            "job": dict(job or {}),
        }
        payload.update(self._dialog_trace_fields())
        return payload

    def _audio_event_payload(self, event: str, **fields) -> dict[str, Any]:
        payload = {
            "event": str(event or ""),
        }
        payload.update(fields)
        payload.update(self._dialog_trace_fields())
        return payload

    def _log_server_event(self, event: str, **fields) -> None:
        payload = self._dialog_trace_fields()
        payload.update(fields)
        log("server", event, **payload)

    def _log_turn_done(self, *, path: str, route: str, elapsed_ms: str, **fields) -> None:
        payload = {
            "path": path,
            "route": route,
            "elapsed_ms": elapsed_ms,
        }
        payload.update(fields)
        self._log_server_event("turn.done", **payload)

    async def send_state(self, state: str):
        """States: IDLE, LISTENING, THINKING, SPEAKING"""
        self._ui_state = str(state or "IDLE")
        await self.send_message("state", self._state_payload(state))

    async def _notify_job_event(self, event: str, job: dict[str, Any]) -> None:
        await self.send_message("job", self._job_event_payload(event, job))
        notification = self._background_completion_notification(event, job)
        if notification:
            self._log_server_event(
                "job.notification",
                event=event,
                job_id=str(job.get("job_id") or ""),
                task_type=str(job.get("task_type") or ""),
            )
            await self.mouth_speak(notification, "neutral")

    async def _notify_audio_event(self, event: str, **fields) -> None:
        await self.send_message("audio", self._audio_event_payload(event, **fields))

    async def interrupt_speech(self, reason: str = "user_input") -> bool:
        self._speech_revision += 1
        if self.mouth is None:
            return False
        interrupted = await asyncio.to_thread(self.mouth.stop_playback)
        if interrupted:
            self._log_server_event("speech.interrupt", reason=reason)
            await self.send_state("LISTENING")
        return bool(interrupted)

    async def _monitor_voice_barge_in(self, speech_revision: int) -> None:
        ears = self.ears
        if not self.audio_orchestrator.should_enable_voice_barge_in(
            text_only_mode=self._text_only_mode,
            ears=ears,
        ):
            return
        while speech_revision == self._speech_revision and str(self._ui_state or "") == "SPEAKING":
            detected = await asyncio.to_thread(ears.detect_voice_activity, 0.2, 2)
            if speech_revision != self._speech_revision:
                return
            if detected:
                await self._notify_audio_event("speech_activity", source="voice_barge_in")
                await self.interrupt_speech(reason="voice_barge_in")
                await self._capture_barge_in_followup(ears)
                return
            await asyncio.sleep(0.02)

    async def _capture_barge_in_followup(self, ears: Any) -> None:
        listen_result = await asyncio.to_thread(ears.listen)
        outcome = self.audio_orchestrator.normalize_listen_result(listen_result)
        if not outcome.has_input:
            return
        turn_id = f"voice-barge-{int(time.time() * 1000)}"
        await self._text_input_queue.put((turn_id, outcome.text))
        await self.send_message(
            "transcription",
            {
                "text": outcome.text,
                "emotion": outcome.emotion,
                "source": "voice_barge_in",
            },
        )
        await self._notify_audio_event(
            "barge_in_captured",
            source="voice_barge_in",
            text_len=len(outcome.text),
        )

    def _background_ack_text(self, task_type: str) -> str:
        task = str(task_type or "")
        if task == "multi_step_or_long_task":
            return "这件事会花一点时间，我先放到后台处理，处理好再告诉你。"
        return "我先放到后台处理，完成后再通知你。"

    def _background_task_label(self, task_type: str) -> str:
        task = str(task_type or "").strip()
        labels = {
            "multi_step_or_long_task": "后台任务",
            "desktop_cleanup": "桌面整理",
            "search": "搜索任务",
            "cleanup": "整理任务",
        }
        return labels.get(task, "后台任务")

    def _should_notify_background_completion(self, event: str, job: dict[str, Any]) -> bool:
        if str(event or "") not in ("completed", "failed"):
            return False
        if not bool(job.get("notify_on_finish", True)):
            return False
        if self.active_websocket is None:
            return False
        return str(self._ui_state or "IDLE") == "IDLE"

    def _background_completion_notification(self, event: str, job: dict[str, Any]) -> str:
        if not self._should_notify_background_completion(event, job):
            return ""
        label = self._background_task_label(str(job.get("task_type") or ""))
        if str(event or "") == "completed":
            return f"{label}完成了。你想听结果的话，我现在就可以继续说。"
        return f"{label}失败了。你要我重试的话，就直接告诉我。"

    async def _process_background_job(self, job: dict[str, Any]) -> dict[str, Any]:
        loop_result = await self.agentic_loop.run(
            user_input=str(job.get("input_text") or ""),
            current_emotion="neutral",
        )
        return {
            "final_text": str(loop_result.final_text or "").strip(),
            "tool_calls_executed": len(loop_result.tool_calls_executed or []),
        }

    async def run_loop(self):
        """The Main Async Event Loop"""
        print("🚀 Starting Main Loop...")
        
        # Start heartbeat if enabled
        if self._heartbeat_enabled:
            try:
                await self.heartbeat.start()
                print("💓 Heartbeat started")
            except Exception as e:
                print(f"⚠️ Heartbeat start failed: {e}")

        # Initial Greeting
        greeting = "Kage 在这。"
        if not self._text_only_mode:
            await self.mouth_speak(greeting)

        # 会话状态
        in_conversation = False  # 是否在对话中
        
        while self.is_running:
            try:
                self._active_turn_id = None
                # --- Check for text input from WebSocket (CLI / frontend) ---
                text_from_ws = None
                turn_id = None
                try:
                    text_from_ws = self._text_input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

                if text_from_ws:
                    if isinstance(text_from_ws, tuple) and len(text_from_ws) >= 2:
                        turn_id = str(text_from_ws[0] or "").strip() or None
                        user_input = str(text_from_ws[1] or "")
                    else:
                        user_input = str(text_from_ws)
                    voice_emotion = "neutral"
                    in_conversation = True
                    self._active_turn_id = turn_id or f"ws-{uuid4().hex[:8]}"
                    print(f"👤 [Text] Master: {user_input}")
                    await self.send_message("transcription", {"text": user_input})
                else:
                    if self._text_only_mode:
                        # Benchmark/CLI mode: no mic capture, text-only loop.
                        await asyncio.sleep(0.05)
                        continue

                    ears = self.ears
                    if ears is None:
                        # Defensive: if ASR failed to initialize, keep loop alive
                        # without touching microphone paths.
                        await asyncio.sleep(0.05)
                        continue

                    # 检查是否需要等待唤醒词
                    if self.audio_orchestrator.should_wait_for_wakeword(in_conversation=in_conversation, ears=ears):
                            # 0. Wake Word Phase (待机模式)
                            # Use short timeout so we can check text_input_queue frequently
                            await self.send_state("IDLE")
                            wakeword_detected = await asyncio.to_thread(ears.wait_for_wakeword, 2)

                            if not wakeword_detected:
                                # 超时，回到循环顶部检查文字输入队列
                                continue

                            # 唤醒成功，先说话再监听 (阻塞模式，避免听到自己的声音)
                            await self.send_message("expression", {"name": "f02", "duration": 1.5})  # surprised
                            await self.mouth_speak("我在，怎么了？", "happy")
                            in_conversation = True

                            # 说完后开始监听
                            await self.send_state("LISTENING")
                            listen_result = await asyncio.to_thread(ears.listen)
                    else:
                        # 已在对话中，直接监听
                        await self.send_state("LISTENING")
                        listen_result = await asyncio.to_thread(ears.listen)

                    outcome = self.audio_orchestrator.normalize_listen_result(listen_result)
                    user_input = outcome.text
                    voice_emotion = outcome.emotion
                    self._active_turn_id = f"voice-{int(time.time() * 1000)}"
                    
                    if not user_input:
                        idle_decision = self.audio_orchestrator.decide_after_empty_input(
                            in_conversation=in_conversation,
                            ears=ears,
                        )
                        if in_conversation and not idle_decision.keep_in_conversation:
                            print("💤 No speech detected, returning to wake word mode")
                        in_conversation = idle_decision.keep_in_conversation
                        await self.send_state(idle_decision.next_ui_state)
                        await asyncio.sleep(idle_decision.sleep_sec)
                        continue
                    
                    print(f"👤 Master: {user_input}")
                    await self.send_message("transcription", {"text": user_input})

                # Determine Emotion early (needed for clarification flows)
                current_emotion: str = "neutral"
                if voice_emotion and voice_emotion != "neutral":
                    current_emotion = str(voice_emotion)
                current_emotion_str = str(current_emotion)
                turn_t0 = time.monotonic()

                def _turn_elapsed_ms() -> str:
                    return f"{((time.monotonic() - turn_t0) * 1000):.1f}"

                route_hint = "chat"
                try:
                    route_hint = self._classify_route_with_assist(str(user_input))
                except Exception:
                    route_hint = "chat"
                realtime_task = classify_realtime_task(str(user_input))
                self._log_server_event("route.hint", route=route_hint, text_len=len(str(user_input or "")))
                self._log_server_event("realtime.classify", lane=realtime_task.lane, reason=realtime_task.reason)

                # Apply correction context early so current turn can use corrected
                # intent instead of re-processing the raw "不是这个，是..." text.
                if self.session.has_pending_action():
                    pa0 = self.session.pending_action
                    if isinstance(pa0, PendingVideoFollowup):
                        early_action = preprocess_video_followup_turn(user_input)
                        if early_action.consume_turn:
                            self.dialog_state.clear_pending()
                            await self.mouth_speak(early_action.speech, current_emotion_str)
                            self._log_turn_done(path="video_followup_cancel_early", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                            continue
                        if early_action.clear_pending and early_action.corrected_input:
                            user_input = early_action.corrected_input
                            self.dialog_state.clear_pending()
                            try:
                                route_hint = self._classify_route_with_assist(str(user_input)) or route_hint
                            except Exception:
                                pass
                            self._log_server_event("video.correction_applied", corrected=user_input)

                # Generic correction: allow "不是这个，是..." to override current turn
                # even without an explicit pending action.
                if not self.session.has_pending_action():
                    generic_corrected = extract_correction_text(str(user_input or ""))
                    if generic_corrected:
                        user_input = generic_corrected
                        try:
                            route_hint = self._classify_route_with_assist(str(user_input))
                        except Exception:
                            pass
                        self._log_server_event("correction.generic_applied", corrected=user_input)

                if realtime_task.lane == "background":
                    job = self.background_lane.submit(
                        task_type=realtime_task.reason,
                        input_text=str(user_input or ""),
                        notify_on_finish=True,
                    )
                    await self._notify_job_event("created", job)
                    await self.mouth_speak(self._background_ack_text(realtime_task.reason), current_emotion_str)
                    self._log_turn_done(
                        path="background_enqueue",
                        route=route_hint,
                        elapsed_ms=_turn_elapsed_ms(),
                        job_id=job.get("job_id"),
                        task_type=job.get("task_type"),
                    )
                    continue

                # High-confidence command fast path (no model): brightness/volume/wifi/bluetooth.
                # This keeps latency low and avoids unnecessary reasoning turns.
                try:
                    command_decision = decide_realtime_command(str(user_input))
                except Exception:
                    command_decision = None
                inferred_name = str(getattr(command_decision, "tool_name", "") or "")
                inferred_conf = float(getattr(command_decision, "confidence", 0.0) or 0.0)
                fastpath_allowed = bool(getattr(command_decision, "mode", "") == "execute" and inferred_name)
                mediumpath_allowed = bool(getattr(command_decision, "mode", "") == "confirm" and inferred_name)
                self._log_server_event(
                    "command.infer",
                    route=route_hint,
                    tool=inferred_name or "none",
                    confidence=f"{float(inferred_conf):.2f}",
                    fastpath=fastpath_allowed,
                    mediumpath=mediumpath_allowed,
                    threshold="0.90",
                )
                if fastpath_allowed and command_decision is not None:
                    await self.send_state("THINKING")
                    name = str(command_decision.tool_name or "")
                    args: dict = dict(command_decision.arguments or {})
                    res = await self.tool_executor.execute(name, args)
                    tc = {
                        "name": name,
                        "arguments": args,
                        "success": res.success,
                        "result": res.result,
                        "error_type": getattr(res, "error_type", None),
                        "error_message": getattr(res, "error_message", None),
                    }
                    reply = self.agentic_loop._command_reply_from_tools([tc])
                    if not reply:
                        reply = self.agentic_loop._fallback_text_from_tools([tc], str(user_input))
                    if not reply:
                        reply = "系统操作已执行。"
                    await self.mouth_speak(reply, current_emotion_str)
                    self._log_turn_done(
                        path="command_fastpath",
                        route=route_hint,
                        tool_elapsed_ms=getattr(res, "elapsed_ms", None),
                        elapsed_ms=_turn_elapsed_ms(),
                    )
                    continue

                if mediumpath_allowed and command_decision is not None:
                    cmd_args: dict[str, Any] = {}
                    raw_cmd_args = command_decision.arguments
                    if isinstance(raw_cmd_args, dict):
                        cmd_args = dict(raw_cmd_args)
                    self.dialog_state.set_pending(
                        make_pending_confirm_inferred_command(
                            str(command_decision.tool_name or ""),
                            cmd_args,
                        )
                    )
                    intent_desc = command_decision.intent_description or describe_command_intent(
                        str(command_decision.tool_name or ""),
                        cmd_args,
                    )
                    await self.mouth_speak(
                        f"我理解你想{intent_desc}。确认就说‘确认’，如果不是这个就说‘不是这个，是…’。",
                        current_emotion_str,
                    )
                    self._log_turn_done(path="command_medium_confirm", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                    continue

                # High-confidence video lookup fast path: preserve user phrase and
                # execute deterministic search without multi-turn model planning.
                if is_video_intent(str(user_input)):
                    await self.send_state("THINKING")
                    low_input = str(user_input or "").lower()
                    wants_open_after_lookup = wants_open_video_action(str(user_input))
                    query_for_video = normalize_video_query_for_search(str(user_input))
                    if not query_for_video:
                        query_for_video = str(user_input)
                    src = "youtube"
                    if any(k in str(user_input) for k in ("b站", "哔哩", "哔哩哔哩")) or "bilibili" in low_input:
                        src = "bilibili"
                    sort = "latest" if any(k in str(user_input) for k in ("最新", "最近", "刚发", "本周", "今日")) else "relevance"
                    video_cache_key = f"video:{src}:{sort}:{str(query_for_video).strip().lower()}"
                    cached_video = self._get_fast_cache(video_cache_key, ttl=300)
                    if cached_video:
                        await self.mouth_speak(str(cached_video), current_emotion_str)
                        self._log_turn_done(path="video_fastpath_cache", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                        continue
                    video_search_t0 = time.monotonic()
                    res = await self.tool_executor.execute(
                        "search",
                        {"query": str(query_for_video), "source": src, "sort": sort, "max_results": 5},
                    )
                    video_search_ms = (time.monotonic() - video_search_t0) * 1000
                    print(f"⏱️ video_fastpath.search_ms={video_search_ms:.1f} query={query_for_video}", flush=True)
                    try:
                        payload = json.loads(str(res.result or "{}"))
                    except Exception:
                        payload = {}
                    items = payload.get("items") if isinstance(payload, dict) else None
                    if isinstance(items, list) and items:
                        top = items[0] if isinstance(items[0], dict) else {}
                        subject = extract_video_subject(str(query_for_video))
                        matched = False
                        if subject:
                            best_score = -1.0
                            best_item = top
                            for it in items:
                                if not isinstance(it, dict):
                                    continue
                                sc = video_subject_match_score(subject, it)
                                if sc > best_score:
                                    best_score = sc
                                    best_item = it
                            if best_score >= 2.0:
                                top = best_item
                                matched = True
                            if not matched:
                                await self.mouth_speak(
                                    f"我暂时没在结果里命中“{subject}”这个博主名（检索耗时约{video_search_ms / 1000:.1f}秒）。你可以说‘不是这个，是完整博主名’让我重试。",
                                    current_emotion_str,
                                )
                                self.dialog_state.set_pending(make_pending_video_followup(source=src, sort=sort))
                                self._log_turn_done(
                                    path="video_fastpath_no_subject_match",
                                    route=route_hint,
                                    tool_elapsed_ms=getattr(res, "elapsed_ms", None),
                                    elapsed_ms=_turn_elapsed_ms(),
                                )
                                continue
                        title = str(top.get("title") or "").strip()
                        url = str(top.get("url") or "").strip()
                        channel = str(top.get("snippet") or "").strip()
                        evidence = video_selection_evidence(subject, top)
                        _ = format_video_evidence(evidence)
                        channel_hint = ""
                        if channel and len(channel) <= 40:
                            channel_hint = f"（频道：{channel}）"
                        if title and url:
                            video_reply = f"我找到一个最新视频候选：{title}{channel_hint}。如果不是这个，你可以说‘不是这个，是…’。"
                            self._set_fast_cache(video_cache_key, video_reply)
                            self.dialog_state.set_pending(
                                make_pending_video_followup(
                                    source=src,
                                    sort=sort,
                                    last_url=url,
                                    last_title=title,
                                    last_channel=channel,
                                )
                            )
                            await self.mouth_speak(video_reply, current_emotion_str)
                            if wants_open_after_lookup:
                                open_t0 = time.monotonic()
                                open_res = await self.tool_executor.execute("open_url", {"url": url})
                                open_ms = (time.monotonic() - open_t0) * 1000
                                print(f"⏱️ video_fastpath.open_ms={open_ms:.1f} url={url}", flush=True)
                                if not open_res.success:
                                    await self.mouth_speak("我找到视频了，但打开浏览器失败。", current_emotion_str)
                            self._log_turn_done(
                                path="video_fastpath",
                                route=route_hint,
                                tool_elapsed_ms=getattr(res, "elapsed_ms", None),
                                elapsed_ms=_turn_elapsed_ms(),
                            )
                            continue
                        if title:
                            await self.mouth_speak(f"我找到一个最新视频候选：{title}。", current_emotion_str)
                            self._log_turn_done(
                                path="video_fastpath",
                                route=route_hint,
                                tool_elapsed_ms=getattr(res, "elapsed_ms", None),
                                elapsed_ms=_turn_elapsed_ms(),
                            )
                            continue

                # Weather fast path: deterministic weather fetch without multi-turn LLM loop.
                if self._weather_fastpath_enabled and "天气" in str(user_input) and not any(k in str(user_input) for k in ("打开", "浏览器", "网页", "网站")):
                    try:
                        await self.send_state("THINKING")
                        reply = await weather_fastpath(
                            str(user_input),
                            agentic_loop=self.agentic_loop,
                            get_fast_cache=self._get_fast_cache,
                            set_fast_cache=self._set_fast_cache,
                            fetch_open_meteo=self._fetch_weather_open_meteo,
                            fetch_metno=self._fetch_weather_metno,
                            fetch_weather_tool_call_quick=self._fetch_weather_tool_call_quick,
                            log_fn=log,
                        )
                        if reply:
                            await self.mouth_speak(reply, current_emotion_str)
                            self._log_turn_done(path="weather_fastpath", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                            continue
                    except Exception:
                        pass

                # High-confidence fast path: undo last file operation
                # (Do not involve the model; keeps latency minimal.)
                if is_undo_request(user_input) and not self.session.has_pending_action():
                    await self.send_state("THINKING")
                    reply = await undo_fastpath(self.tool_executor)
                    await self.mouth_speak(reply, current_emotion_str)
                    self._log_turn_done(path="undo_fastpath", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                    continue

                # If we previously asked for confirmation, consume it here.
                if self.session.has_pending_action():
                    pa = self.session.pending_action
                    if pending_requires_thinking(pa):
                        await self.send_state("THINKING")
                    pending_result = await handle_pending_action(
                        pending=pa,
                        user_input=str(user_input or ""),
                        current_emotion=current_emotion_str,
                        tool_executor=self.tool_executor,
                        make_pending_followup=PendingVideoFollowup,
                        agentic_loop=self.agentic_loop,
                        classify_route=self._classify_route_with_assist,
                        is_undo_request=is_undo_request,
                        infer_chat_topic=self._infer_chat_topic,
                        structured_chat_followup=self._structured_chat_followup,
                        polish_chat_response=self._polish_chat_response,
                        think_action=self._think_action,
                        history_provider=self.session.as_history_list,
                    )
                    self.dialog_state.apply_pending_result(pending_result)
                    if pending_result.handled:
                        if pending_result.speech:
                            final_speech = pending_result.speech
                            if pending_result.record_turn:
                                print(f"👻 Kage: {final_speech}")
                            await self.mouth_speak(final_speech, current_emotion_str)
                            if pending_result.record_turn:
                                try:
                                    self.session.add_turn("user", user_input)
                                    self.session.add_turn("assistant", str(final_speech))
                                except Exception:
                                    pass
                        self._log_turn_done(path=pending_result.log_path or "pending_action", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                        continue
                    if pending_result.run_agent_loop:
                        user_input = pending_result.new_user_input or str(user_input or "")
                        if pending_result.new_route_hint:
                            route_hint = pending_result.new_route_hint
                        loop_result = await self.agentic_loop.run(
                            user_input=str(user_input or ""),
                            current_emotion=current_emotion_str,
                        )
                        final_speech = loop_result.final_text
                        await self.mouth_speak(final_speech, current_emotion_str)
                        self._log_turn_done(path="confirm_inferred_fallback", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                        continue
                    if pending_result.preserve_pending:
                        pass

                # 2. Thinking Phase
                await self.send_state("THINKING")

                # Unified agentic loop (model -> tools -> observe -> model)
                loop_result = await self.agentic_loop.run(
                    user_input=user_input,
                    current_emotion=current_emotion_str,
                )
                final_speech = loop_result.final_text
                executed_tools = bool(loop_result.tool_calls_executed)

                # If a tool requests confirmation, ask the user and pause.
                need_confirm = None
                try:
                    for tc in (loop_result.tool_calls_executed or []):
                        if tc.get("error_type") == "NeedConfirmation":
                            need_confirm = tc
                except Exception:
                    need_confirm = None

                if need_confirm:
                    tool_name = str(need_confirm.get("name") or "").strip()
                    tool_args = need_confirm.get("arguments") or {}
                    preview = str(need_confirm.get("error_message") or "").strip()
                    self.dialog_state.set_pending(
                        make_pending_confirm_tool(tool_name, tool_args)
                    )
                    await self.mouth_speak(f"要执行删除类操作：{preview}\n确认吗？回复‘确认’或‘取消’。", current_emotion_str)
                    self._log_turn_done(path="need_confirmation", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                    continue

                # NOTE: legacy chat post-processing removed in unified loop.

                print(f"👻 Kage: {final_speech}")
                await self.mouth_speak(final_speech, current_emotion_str)
                self._log_turn_done(path="agentic_loop", route=route_hint, elapsed_ms=_turn_elapsed_ms())

                # Update short-term history
                try:
                    self.session.add_turn("user", user_input)
                    self.session.add_turn("assistant", str(final_speech))
                except Exception:
                    pass
                # Persist to session_manager (file-backed)
                try:
                    self.session_manager.add_turn("user", user_input)
                    self.session_manager.add_turn("assistant", str(final_speech))
                except Exception:
                    pass

                # Save memory only for chat
                if not executed_tools:
                    try:
                        self.memory.add_memory(content=user_input, emotion=current_emotion_str, type="chat")
                    except Exception:
                        pass

                continue

            except Exception as e:
                print(f"❌ Error in loop: {e}")
                traceback.print_exc()
                log("server", "turn.error", error=str(e))
                await asyncio.sleep(1)

    def _think_action(self, user_input: str, memories: list, history: list, current_emotion: str, mode: str):
        # Compatibility wrapper (some legacy paths still call this).
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": str(user_input or "")},
        ]
        try:
            resp = self.model_provider.generate(messages=messages, tools=None, max_tokens=200, temperature=0.7)
            return [str(getattr(resp, "text", "") or "")]
        except Exception as exc:
            return [f"模型调用失败: {exc}"]

    def _think_report(self, report_input: str, current_emotion: str):
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": str(report_input or "")},
        ]
        try:
            return self.model_provider.generate(messages=messages, tools=None, max_tokens=200, temperature=0.7)
        except Exception as exc:
            from core.model_provider import ModelResponse

            return ModelResponse(text=f"模型调用失败: {exc}", emotion="sad")

    # NOTE: Legacy tool-loop/router removed. The runtime uses AgenticLoop + ToolExecutor.

    async def mouth_speak(self, text, emotion="neutral"):
        """Speak and allow Frontend to sync lips and expression"""
        text = self._sanitize_for_speech(text)
        if not text:
            return
        self._speech_revision += 1
        speech_revision = self._speech_revision

        # Text-only benchmark mode: skip TTS playback and only emit speech message.
        if self._text_only_mode or self.mouth is None:
            await self.send_message("speech", {"text": text, "emotion": emotion})
            if speech_revision == self._speech_revision:
                await self.send_state("IDLE")
            return

        try:
            print(f"🗣️ TTS request ({emotion}): {text}", flush=True)
        except Exception:
            pass

        self._update_motion_cooldown(text)
        await self._send_random_motion(emotion)
        
        # 1. Send Expression (Emotion)
        exp_value = self.expression_map.get(emotion, "f05")
        if isinstance(exp_value, dict):
            choices = exp_value.get("choices") or []
            weights = exp_value.get("weights")
            if choices:
                if weights and len(weights) == len(choices):
                    exp_name = random.choices(choices, weights=weights, k=1)[0]
                else:
                    exp_name = random.choice(choices)
            else:
                exp_name = "f05"
        elif isinstance(exp_value, list):
            exp_name = random.choice(exp_value) if exp_value else "f05"
        else:
            exp_name = exp_value
        await self.send_message("expression", {
            "name": exp_name,
            "duration": self._compute_expression_duration(text),
        })

        # 2. Send text to frontend (for speech bubble) with emotion field
        await self.send_message("speech", {"text": text, "emotion": emotion})
        
        # 3. Audio Generation (Generating... not speaking yet)
        audio_path = await self.mouth.generate_speech_file(text, emotion)
        if speech_revision != self._speech_revision:
            return
        
        if audio_path:
            try:
                print(f"🔊 Playing audio: {audio_path}", flush=True)
            except Exception:
                pass
            # 4. Now we are ready to play. Signal Frontend!
            await self.send_state("SPEAKING")
            barge_task = None
            if self.audio_orchestrator.should_enable_voice_barge_in(
                text_only_mode=self._text_only_mode,
                ears=self.ears,
            ):
                barge_task = asyncio.create_task(self._monitor_voice_barge_in(speech_revision))
            # Blocking Playback
            try:
                await asyncio.to_thread(self.mouth.play_audio_file, audio_path)
            finally:
                if barge_task is not None:
                    barge_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await barge_task
            # Done
            if speech_revision == self._speech_revision:
                await self.send_state("IDLE")
        else:
            try:
                print("⚠️ TTS generation failed (no audio_path)", flush=True)
            except Exception:
                pass
            if speech_revision == self._speech_revision:
                await self.send_state("IDLE")

    def _sanitize_for_speech(self, text: str) -> str:
        """Remove system artifacts and keep speech user-facing."""
        return sanitize_for_speech_text(text)

    def _classify_route_with_assist(self, user_input: str) -> str:
        """Rule-first route classification with optional model assist for ambiguity."""
        base = "chat"
        try:
            base = str(self.prompt_builder.classify_route(str(user_input or "")) or "chat")
        except Exception:
            base = "chat"

        if not self._route_model_assist_enabled:
            return base
        if not self._is_route_ambiguous(str(user_input or ""), base):
            return base

        try:
            assisted = self._classify_route_by_model(str(user_input or ""))
            if assisted in ("command", "info", "chat"):
                log("server", "route.assist", base=base, assisted=assisted)
                return assisted
        except Exception:
            pass
        return base

    @staticmethod
    def _is_route_ambiguous(user_input: str, base_route: str) -> bool:
        s = str(user_input or "").strip().lower()
        if not s:
            return False
        system_hits = sum(1 for k in ("打开", "关闭", "调高", "调低", "音量", "亮度", "wifi", "蓝牙") if k in s)
        info_hits = sum(1 for k in ("查", "搜索", "搜", "天气", "新闻", "价格", "汇率", "视频") if k in s)
        if base_route == "chat":
            return bool(system_hits or info_hits)
        if base_route == "command" and info_hits >= 2:
            return True
        if base_route == "info" and system_hits >= 2:
            return True
        return False

    def _classify_route_by_model(self, user_input: str) -> str:
        """Use lightweight model call for ambiguous route classification."""
        system = (
            "你是路由分类器。只输出一个词：command 或 info 或 chat。"
            "command=执行动作/系统控制；info=查询信息；chat=闲聊。"
        )
        user = f"用户输入：{str(user_input or '').strip()}\n只输出一个词。"
        resp = self.model_provider.generate(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=None,
            max_tokens=8,
            temperature=0.0,
        )
        text = str(getattr(resp, "text", "") or "").strip().lower()
        if "command" in text:
            return "command"
        if "info" in text:
            return "info"
        return "chat"

    def _fetch_weather_tool_call_quick(self, city: str) -> dict | None:
        """Fetch wttr JSON quickly and convert to tool-call-like payload."""
        try:
            import urllib.request

            url = f"https://wttr.in/{quote(str(city or 'Shanghai'))}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "Kage/1.0"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if not isinstance(data, dict):
                return None
            payload = {"success": True, "content": json.dumps(data, ensure_ascii=False)}
            return {"name": "web_fetch", "success": True, "result": json.dumps(payload, ensure_ascii=False)}
        except Exception:
            return None

    async def _send_random_motion(self, emotion: str | None = None):
        if not self.motion_groups:
            return
        now = time.monotonic()
        if now - self._last_motion_time < self.motion_cooldown_sec:
            return
        self._last_motion_time = now
        emotion_key = emotion or ""
        weights_map = self.motion_emotion_weights.get(emotion_key, self.motion_group_weights)
        groups = list(weights_map.keys())
        weights = list(weights_map.values())
        group = random.choices(groups, weights=weights, k=1)[0]
        max_index = self.motion_groups.get(group, 0)
        if max_index <= 0:
            return
        index = random.randrange(max_index)
        await self.send_message("motion", {"group": group, "index": index})

    def _update_motion_cooldown(self, text: str):
        if not text:
            return
        duration = self.expression_duration_base_sec + len(text) * 0.06
        self.motion_cooldown_sec = max(
            self.motion_cooldown_min_sec,
            min(duration, self.motion_cooldown_max_sec),
        )

    def _compute_expression_duration(self, text: str) -> float:
        if not text:
            return self.expression_duration_base_sec
        duration = self.expression_duration_base_sec + len(text) * self.expression_duration_per_char
        return max(
            self.expression_duration_min_sec,
            min(duration, self.expression_duration_max_sec),
        )

    def _quick_chat_response(self, user_input: str):
        text = (user_input or "").strip()
        if not text:
            return None

        # Location correction (used by local weather queries)
        try:
            # "我不在巴黎 我在尼斯"
            m = re.search(r"我不在([A-Za-z\u4e00-\u9fff]{2,})\s*.*我在([A-Za-z\u4e00-\u9fff]{2,})", text)
            if m:
                city = m.group(2)
                self._set_location_override(city)
                return f"好，我记下了，你在{city}。"
            # "我在尼斯" / "我现在在尼斯"
            m = re.search(r"我(?:现在)?在\s*([A-Za-z\u4e00-\u9fff]{2,})", text)
            if m and "天气" not in text:
                city = m.group(1)
                # avoid obvious filler/time tokens
                if city not in ("今天", "今晚", "晚上", "明天", "后天", "这里", "本地", "当地"):
                    self._set_location_override(city)
                    return f"好，你在{city}。"
        except Exception:
            pass

        if "你是谁" in text:
            return "我是 Kage。"
        if "你能做什么" in text:
            return "系统控制/计算/文件操作。"
        if any(k in text for k in ["你执行成功什么", "你成功什么", "你做了什么", "你刚做了什么", "你干了什么"]):
            try:
                la = (self.session.last_action if hasattr(self, "session") else None) or {}
                if la.get("type") == "weather" and la.get("result"):
                    return f"我刚查了天气：{la.get('result')}"
                if la.get("summary"):
                    return str(la.get("summary"))
            except Exception:
                pass
            return "我刚处理了一个操作，你再说一遍你的问题？"
        if "冷笑话" in text or "笑话" in text:
            return "我当然会讲，不过这个版本的笑话技能还没装上。你想让我做点实际的事吗？"
        return None

    def _quick_chat_plan(self, user_input: str):
        """Return a (reply, pending_action) tuple for lightweight multi-turn chat."""
        text = (user_input or "").strip()
        if not text:
            return None, None

        reply = self._quick_chat_response(text)
        if not reply:
            return None, None

        reply_s = str(reply)

        # If we ask a clarification question, set pending chat follow-up.
        needs_followup = False
        topic = self._infer_chat_topic(text)
        if reply_s in (
            "你是想问天气，还是安排？",
            "你想表达什么，给谁看？",
            "你卡在哪一步？",
            "把内容发我，我帮你看。",
            "他发了啥？你想怎么回？",
            "你想怎么说？我帮你拟一句。",
        ):
            needs_followup = True

        pending = None
        if needs_followup:
            pending = make_pending_chat_followup(topic=str(topic or ""), asked=reply_s)
        return reply_s, pending

    def _should_try_tools(self, user_input: str) -> bool:
        """Heuristic: route to action mode so the LLM can choose tools.

        Keep this broad (not app/site specific) to preserve generalization.
        """
        text = (user_input or "").strip()
        if not text:
            return False
        lower_text = text.lower()

        # Explicit imperative / help request.
        if any(tok in text for tok in ["帮我", "请帮", "麻烦", "给我", "能不能"]):
            return True

        # Requests likely needing external data or tool execution.
        toolish = [
            "打开", "关闭", "启动", "开启", "退出",
            "查询", "查", "搜索", "搜", "找", "推荐",
            "下载", "安装",
            "截图", "截屏",
            "音量", "亮度", "wifi", "蓝牙",
            "网址", "链接", "网站", "网页",
        ]
        if any(tok in text for tok in toolish):
            return True

        # English tool-ish.
        if any(tok in lower_text for tok in ["open ", "close ", "search", "download", "install", "url", "link"]):
            return True

        return False

    def _is_bad_chat_response(self, text: str, user_input: str) -> bool:
        t = (text or "").strip()
        if not t:
            return True

        # Avoid unintended English unless user used English.
        import re
        ui = (user_input or "").strip()
        if re.search(r"[A-Za-z]", t) and not re.search(r"[A-Za-z]", ui):
            return True
        # Too short often sounds robotic.
        if len(t) <= 2 and t not in ("嗯", "好", "行", "OK"):
            return True
        # Rude / refusal patterns.
        bad_phrases = [
            "我不是你的朋友",
            "不关我的事",
            "我不想",
            "我不知道",
            "我不清楚",
            "无法回答",
            "无法处理",
        ]
        if any(p in t for p in bad_phrases):
            return True
        # Off-topic generic filler.
        if t in ("执行成功。", "成功。", "不知道。"):
            return True
        # If user asked for help, a super short reply is usually not helpful.
        if any(k in ui for k in ("帮我", "怎么", "为什么", "怎么样")) and len(t) < 4:
            return True

        # Generic acknowledgements that are not helpful.
        generic = {"明白了", "知道了", "了解", "好的", "好", "行", "嗯", "OK", "好的。", "好。", "行。", "嗯。"}
        if t in generic and len(ui) >= 6:
            return True
        return False

    async def _repair_chat_response(
        self,
        user_input: str,
        draft: str,
        memories: list,
        history: list,
        current_emotion: str,
    ) -> str:
        """Second-pass rewrite to keep LLM feel without hardcoded replies."""
        # Keep it short and purely a rewrite instruction.
        repair_input = (
            "把下面回复改写得更像真人、更有帮助。\n"
            "要求：中文；1-2 句；先回应用户意图/情绪；再给建议或追问 1 个问题；不要自我介绍；不要输出英文。\n"
            f"用户：{user_input}\n"
            f"原回复：{draft}\n"
            "只输出改写后的回复。"
        )

        response_stream = await asyncio.to_thread(  # type: ignore[arg-type]
            self._think_action,
            repair_input,
            memories,
            history,
            current_emotion,
            "chat",
        )
        out = ""
        for chunk in response_stream:
            out += getattr(chunk, "text", str(chunk))
        return self._polish_chat_response(out)

    def _fallback_chat_response(self, user_input: str) -> str:
        text = (user_input or "").strip()
        if any(k in text for k in ("谢谢", "感谢")):
            return "不客气。"
        return "我在。你想让我怎么帮你？"

    def _infer_chat_topic(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        if "朋友圈" in t or "发这条" in t:
            return "moments"
        if "怎么回" in t:
            return "reply"
        if "道歉" in t:
            return "apology"
        if any(k in t for k in ["怎么弄", "怎么做", "怎么搞"]):
            return "howto"
        if "今天晚上" in t or "今晚" in t:
            return "tonight"
        return ""

    def _structured_chat_followup(self, topic: str, user_input: str) -> str | None:
        """Rule-based followups for product-grade reliability.

        This is used when we explicitly asked for clarification and want a stable,
        helpful answer without relying on the model to stay on-rails.
        """
        text = (user_input or "").strip()
        if not text:
            return None

        if topic == "moments":
            # Friend circle advice + one copy-ready caption.
            audience = "同学" if "同学" in text else "朋友" if "朋友" in text else "大家"
            if "考完" in text or "考试" in text:
                caption = "考试终于结束啦，辛苦自己了。接下来好好休息一下。"
            else:
                caption = f"{text}"
                if len(caption) < 8:
                    caption = f"{caption}。"
            return f"建议发给{audience}。文案：{caption}"

        if topic == "apology":
            # One-line apology template.
            return "你可以这样说：刚刚我语气有点冲，对不起。我很在乎你，想好好说。"

        if topic == "reply":
            return "把对方原话贴我，我给你拟一句更贴合的回复。"

        if topic == "howto":
            return "你先告诉我：你现在卡在哪一步、目标是什么？"

        if topic == "tonight":
            return "你是想问天气，还是今晚的安排？"

        return None

    def _polish_chat_response(self, text: str):
        if not text:
            return text
        import re
        cleaned = strip_reasoning_artifacts(text)
        cleaned = " ".join(cleaned.split())

        # Strip user-echo patterns: model sometimes repeats user input back
        # e.g. "用户：帮我找... 助手：请问你在哪里查看"
        cleaned = re.sub(r"用户[：:]\s*.*?助手[：:]\s*", "", cleaned)
        # Also strip standalone "用户：..." prefix
        cleaned = re.sub(r"^用户[：:]\s*.*$", "", cleaned, flags=re.MULTILINE)

        # Strip system tool/runtime artifacts if they ever leak into speech.
        cleaned = sanitize_for_speech_text(cleaned)
        cleaned = cleaned.replace("Master心情:", "")
        cleaned = cleaned.replace("Master心情", "")
        cleaned = cleaned.replace("Master 心情:", "")
        cleaned = cleaned.replace("Master 心情", "")
        cleaned = cleaned.replace("@@@", "")

        # Normalize addressing.
        cleaned = cleaned.replace("Master", "你")


        # Remove capability brag / meta descriptions that frequently leak from persona.
        cleaned = re.sub(r"我能做[^。！？!]*[。！？!]*", "", cleaned)
        cleaned = re.sub(r"\d+\s*项\s*事\s*[:：]\s*", "", cleaned)
        cleaned = re.sub(r"项\s*事\s*[:：]\s*", "", cleaned)

        cleaned = self._filter_chat_text(cleaned)
        cleaned = self._collapse_repeats(cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            cleaned = "嗯"

        # Strip trailing filler particles.
        cleaned = re.sub(r"\s*[哒捏哇]+\s*(?:[!！。.]*)\s*$", "", cleaned).strip()

        # Strip leading decorative marks.
        cleaned = re.sub(r"^[\s✨😤💖]+", "", cleaned).strip()
        if not cleaned:
            cleaned = "嗯"

        max_len = 40
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len]
        return cleaned

    def _fast_command(self, user_input: str):
        text = (user_input or "").strip()
        if not text:
            return None

        lower_text = text.lower()

        # Weather queries should not be confused with network (WiFi) controls.
        # If user explicitly asks to search the web, use web_search instead.
        if "天气" in text and any(tok in text for tok in ["网络", "网上", "搜索", "搜一下", "网络搜", "网络查询"]):
            city = self._extract_city(text)
            if not city:
                city = self._get_effective_city() or ""
            q = f"{city} 天气".strip() if city else "天气"
            print("🧭 Direct: web_search -> weather")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "web_search"):
                try:
                    return tools.web_search(q, max_results=3)
                except Exception:
                    pass
            from core.tools_impl import smart_search
            return smart_search(q, max_results=3)

        if "天气" in text:
            city = self._extract_city(text)
            if city in ("所以", "现在", "我现在"):
                city = ""
            if not city:
                city = self._get_effective_city() or "Beijing"
                cached_weather = self._get_fast_cache("weather:local", ttl=1800)
                if cached_weather:
                    self.session.last_action = {
                        "type": "weather",
                        "result": cached_weather,
                        "summary": "我刚查了本地天气。",
                    }
                    return cached_weather
            city_map = {"尼斯": "Nice"}
            city = city_map.get(city, city)
            print("🧭 Direct: run_cmd -> wttr.in")
            weather = self._fetch_weather(city)
            self.session.last_action = {"type": "weather", "result": weather, "summary": "我刚查了天气。"}
            return weather
        if "亮度" in text:
            action = "up"
            if any(token in text for token in ["低", "暗", "小", "降低", "调低", "调暗"]):
                action = "down"
            print("🧭 Direct: system_control -> brightness")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "system_control"):
                return tools.system_control("brightness", action)
            from core.tools_impl import system_control
            return system_control("brightness", action)

        # 独立的静音命令
        if "静音" in text or "mute" in lower_text:
            action = "unmute" if "取消" in text or "un" in lower_text else "mute"
            print("🧭 Direct: system_control -> mute")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "system_control"):
                return tools.system_control("volume", action)
            from core.tools_impl import system_control
            return system_control("volume", action)

        if "音量" in text or "声音" in text:
            action = "up"
            if any(token in text for token in ["小", "低", "降低", "调低"]):
                action = "down"
            print("🧭 Direct: system_control -> volume")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "system_control"):
                return tools.system_control("volume", action)
            from core.tools_impl import system_control
            return system_control("volume", action)

        # 媒体控制 - 扩展关键词匹配
        media_keywords = ["播放", "暂停", "继续", "下一首", "下一曲", "上一首", "上一曲", 
                          "放音乐", "放歌", "放点歌", "来点歌", "听歌", "听音乐", "停止播放", "停止音乐"]
        if any(token in text for token in media_keywords):
            action = "playpause"
            if "下一" in text:
                action = "next"
            elif "上一" in text:
                action = "previous"
            elif "暂停" in text:
                action = "pause"
            elif "继续" in text or "播放" in text:
                action = "play"
            print("🧭 Direct: media_control")
            preferred_apps = []
            if "网易云" in text or "云音乐" in text:
                preferred_apps = ["NeteaseMusic", "网易云音乐"]
            elif "spotify" in lower_text:
                preferred_apps = ["Spotify"]
            return self._media_control(action, preferred_apps)

        if "蓝牙" in text:
            action = "off" if any(token in text for token in ["关", "关闭", "关掉"] ) else "on"
            print("🧭 Direct: system_control -> bluetooth")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "system_control"):
                return tools.system_control("bluetooth", action)
            from core.tools_impl import system_control
            return system_control("bluetooth", action)

        # WiFi control: avoid matching generic "网络" in informational questions.
        wifi_control = False
        if "wifi" in lower_text or "wi-fi" in lower_text:
            wifi_control = True
        if any(tok in text for tok in ["无线网", "无线网络", "WiFi", "WIFI", "wifi"]):
            wifi_control = True
        if "网络" in text and any(tok in text for tok in ["打开", "关闭", "开", "关", "开启", "关掉", "断开", "连接"]):
            wifi_control = True

        if wifi_control and not any(tok in text for tok in ["查询", "搜索", "网络查询", "网上", "怎么样", "怎么", "为啥"]):
            action = "off" if any(token in text for token in ["关", "关闭", "关掉"] ) else "on"
            print("🧭 Direct: system_control -> wifi")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "system_control"):
                return tools.system_control("wifi", action)
            from core.tools_impl import system_control
            return system_control("wifi", action)


        # 网站/应用打开交给大模型 action tool-calls，以获得更好的泛化能力。

        # 网站快捷打开 - 必须是"打开"而非"关闭"
        is_open_action = "打开" in text or "open" in lower_text
        is_close_action = "关闭" in text or "close" in lower_text or "退出" in text

        # 关闭应用快速路径
        if is_close_action and not is_open_action:
            # 匹配关闭的目标
            close_match = re.search(r"(?:关闭|退出|关掉)(.+)", text)
            if close_match:
                target = close_match.group(1).strip(" ：:，,。\n\t吧请")
                # 网站 -> 关闭浏览器
                if any(site in target for site in ["b站", "哔哩哔哩", "知乎", "百度", "网页", "浏览器"]):
                    print(f"🧭 Direct: close_app -> Safari (网页)")
                    from core.tools_impl import system_control
                    return system_control("app", "close", "Safari")
                # 其他应用
                if target:
                    print(f"🧭 Direct: close_app -> {target}")
                    from core.tools_impl import system_control
                    return system_control("app", "close", target)

        if "几点" in text or "时间" in text:
            print("🧭 Direct: get_time")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "get_time"):
                return self._persona_wrap(tools.get_time(), "time")
            from core.tools_impl import get_time
            return self._persona_wrap(get_time(), "time")

        if "截图" in text or "截屏" in text:
            print("🧭 Direct: take_screenshot")
            tools = getattr(self, "tools", None)
            if tools is not None and hasattr(tools, "take_screenshot"):
                return self._persona_wrap(tools.take_screenshot(), "screenshot")
            from core.tools_impl import take_screenshot
            return self._persona_wrap(take_screenshot(), "screenshot")

        if "电量" in text or "电池" in text:
            print("🧭 Direct: battery_status")
            import subprocess
            try:
                out = subprocess.check_output(["pmset", "-g", "batt"], text=True)
            except Exception:
                out = ""
            m = re.search(r"(\d+%)", out)
            battery = m.group(1) if m else ""
            return self._persona_wrap(f"电量 {battery}", "battery")

        return None

    def _persona_wrap(self, result: str, cmd_type: str = "default") -> str:
        """给快速命令结果添加 persona 风格"""
        import random
        
        # 根据命令类型选择回复风格
        templates = {
            "time": ["现在是 {r}", "时间是 {r}"],
            "weather": ["天气：{r}", "查到了：{r}"],
            "screenshot": ["截图完成：{r}", "截好了：{r}"],
            "battery": ["电量：{r}", "还有电：{r}"],
            "volume": ["{r}"],
            "brightness": ["{r}"],
            "media": ["{r}"],
            "app": ["{r}"],
            "default": ["{r}"],
        }
        
        # 获取模板并格式化
        template_list = templates.get(cmd_type, templates["default"])
        template = random.choice(template_list)
        return template.format(r=str(result).strip())

    def _get_local_city(self):
        cached = self._get_fast_cache("local_city", ttl=86400)
        if cached:
            return cached
        city = ""
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://ipinfo.io/city",
                headers={"User-Agent": "Kage/1.0"},
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                city = (resp.read().decode("utf-8", errors="replace") or "").strip()
        except Exception:
            city = ""
        if city:
            self._set_fast_cache("local_city", city)
            return city
        return ""

    def _set_location_override(self, city: str):
        c = str(city or "").strip().strip(" ：:，,。\n\t")
        if not c:
            return
        self._set_fast_cache("location_override", c)

    def _get_effective_city(self) -> str:
        override = self._get_fast_cache("location_override", ttl=86400)
        if override:
            return str(override)
        return self._get_local_city() or ""

    def _fetch_weather_open_meteo(self, city: str, day_offset: int = 0) -> str:
        """Open-Meteo provider (no API key), supports today/tomorrow."""
        import json
        import urllib.parse
        import urllib.request

        name = str(city or "").strip()
        if not name:
            return ""

        coords = self._resolve_weather_coords(name)
        if not coords:
            return ""
        lat, lon, disp = coords

        # 2) Forecast + daily
        forecast_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                    "timezone": "auto",
                }
            )
        )
        req2 = urllib.request.Request(forecast_url, headers={"User-Agent": "Kage/1.0"})
        with urllib.request.urlopen(req2, timeout=3) as resp:
            data2 = json.loads(resp.read().decode("utf-8", errors="replace"))
        cw = data2.get("current_weather") or {}
        temp = cw.get("temperature")
        code = cw.get("weathercode")
        if temp is None:
            return ""

        desc_map = {
            0: "晴",
            1: "多云",
            2: "多云",
            3: "阴",
            45: "雾",
            48: "雾",
            51: "小毛毛雨",
            53: "毛毛雨",
            55: "大毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            80: "阵雨",
            81: "阵雨",
            82: "强阵雨",
            95: "雷阵雨",
        }
        try:
            code_i = int(code) if code is not None else None
        except Exception:
            code_i = None
        desc = desc_map.get(code_i, "天气") if code_i is not None else "天气"
        try:
            t = int(round(float(temp)))
        except Exception:
            t = temp
        when = "明天" if int(day_offset or 0) == 1 else "今天"

        daily = data2.get("daily") or {}
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        dcode = daily.get("weather_code") or []
        idx = 1 if int(day_offset or 0) == 1 else 0
        hi = tmax[idx] if isinstance(tmax, list) and len(tmax) > idx else None
        lo = tmin[idx] if isinstance(tmin, list) and len(tmin) > idx else None
        dc = dcode[idx] if isinstance(dcode, list) and len(dcode) > idx else code
        try:
            dc_i = int(dc) if dc is not None else None
        except Exception:
            dc_i = None
        ddesc = desc_map.get(dc_i, desc) if dc_i is not None else desc

        if hi is not None and lo is not None:
            try:
                hi_v = int(round(float(hi)))
                lo_v = int(round(float(lo)))
                return f"{disp}{when}，{ddesc}，气温{lo_v}到{hi_v}度，当前{t}度。"
            except Exception:
                pass
        return f"{disp}{when}，{ddesc}，当前{t}度。"

    def _fetch_weather_metno(self, city: str) -> str:
        """MET Norway provider (no API key, requires User-Agent)."""
        import json
        import urllib.parse
        import urllib.request

        coords = self._resolve_weather_coords(str(city or ""))
        if not coords:
            return ""
        lat, lon, disp = coords

        url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?" + urllib.parse.urlencode(
            {"lat": lat, "lon": lon}
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Kage/1.0 (kage assistant)"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        ts = ((data.get("properties") or {}).get("timeseries") or [])
        if not ts:
            return ""
        first = ts[0] if isinstance(ts[0], dict) else {}
        details = (((first.get("data") or {}).get("instant") or {}).get("details") or {})
        temp = details.get("air_temperature")
        if temp is None:
            return ""
        try:
            t = int(round(float(temp)))
        except Exception:
            t = temp
        return f"{disp}今天，当前约{t}度。"

    def _resolve_weather_coords(self, city: str) -> tuple[float, float, str] | None:
        """Resolve city to coordinates with cache."""
        import json
        import urllib.parse
        import urllib.request

        name = str(city or "").strip()
        if not name:
            return None
        key = f"weather_coords:{name.lower()}"
        cached = self._get_fast_cache(key, ttl=86400)
        if cached:
            try:
                o = json.loads(str(cached))
                lat = float(o.get("lat"))
                lon = float(o.get("lon"))
                disp = str(o.get("name") or name)
                return (lat, lon, disp)
            except Exception:
                pass

        geocode_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": name, "count": 1, "language": "zh", "format": "json"})
        )
        req = urllib.request.Request(geocode_url, headers={"User-Agent": "Kage/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        results = data.get("results") or []
        if not results:
            return None
        r0 = results[0]
        lat = r0.get("latitude")
        lon = r0.get("longitude")
        disp = r0.get("name") or name
        if lat is None or lon is None:
            return None
        out = {"lat": lat, "lon": lon, "name": disp}
        self._set_fast_cache(key, json.dumps(out, ensure_ascii=False))
        return (float(lat), float(lon), str(disp))

    def _prefetch_local_city(self):
        try:
            self._get_local_city()
        except Exception:
            pass

    def _get_fast_cache(self, key: str, ttl: int):
        entry = self._fast_cache.get(key)
        if not entry:
            return ""
        if time.time() - entry["timestamp"] > ttl:
            self._fast_cache.pop(key, None)
            return ""
        return entry["value"]

    def _set_fast_cache(self, key: str, value: str):
        self._fast_cache[key] = {"timestamp": time.time(), "value": value}

    def _strip_cmd_output(self, result) -> str:
        text = str(result).strip()
        if text.startswith("命令执行成功"):
            parts = text.splitlines()
            return parts[-1] if parts else ""
        return text

    def _fetch_weather(self, city: str) -> str:
        local_city = self._get_local_city() or ""
        cache_key = "weather:local" if city == local_city else f"weather:{city.lower()}"
        cached_weather = self._get_fast_cache(cache_key, ttl=1800)
        if cached_weather:
            return cached_weather
        weather = ""
        try:
            import urllib.request
            url = f"https://wttr.in/{quote(city)}?format=3"
            req = urllib.request.Request(url, headers={"User-Agent": "Kage/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                weather = (resp.read().decode("utf-8", errors="replace") or "").strip()
        except Exception:
            weather = ""
        # Handle timeouts / curl failures / empty output gracefully.
        if (
            not weather
        ):
            # Fallback: use a second provider (Open-Meteo) if available.
            try:
                alt = self._fetch_weather_open_meteo(city)
                if alt:
                    self._set_fast_cache(cache_key, alt)
                    return alt
            except Exception:
                pass
            fallback = self._get_fast_cache(cache_key, ttl=86400)
            return fallback or "天气查询超时了，等会儿再试。"
        if weather:
            self._set_fast_cache(cache_key, weather)
            return weather
        fallback = self._get_fast_cache(cache_key, ttl=86400)
        return fallback or "天气查询失败，请稍后再试"

    def _extract_city(self, text: str) -> str:
        # If the user already corrected location, prefer that mention.
        try:
            override = self._get_fast_cache("location_override", ttl=86400)
            if override and str(override) in text:
                return str(override)
        except Exception:
            pass

        cleaned = text
        stopwords = [
            "天气", "怎么样", "如何", "今天", "现在", "查询", "查", "一下", "看看", "帮我",
            "的", "吗", "么", "呀", "啊", "呢", "是不是", "想", "告诉我",
            "我说", "我想", "我问", "我", "说", "问",
            "晚上", "今晚上", "今晚", "明天", "后天", "上午", "下午", "早上", "中午",
            "嗯", "嗯嗯", "额", "呃", "啊", "唉", "em",
            "当地", "本地", "这里", "我这", "我们这",
            "所以", "那", "然后", "不过", "就是", "此刻",
            "去", "去查", "去看看", "去问", "帮我查", "帮我问",
            "网络", "网上", "搜索", "搜", "搜下", "搜一下", "网络搜", "网络查询", "网络搜一下",
        ]
        # Replace longer phrases first to avoid leaving fragments.
        for word in sorted(stopwords, key=len, reverse=True):
            cleaned = cleaned.replace(word, "")
        cleaned = cleaned.strip(" ：:，,。\n\t")
        if not cleaned:
            return ""
        matches = re.findall(r"[A-Za-z\u4e00-\u9fff]+", cleaned)
        if not matches:
            return ""
        candidate = max(matches, key=len)
        for prefix in ("去", "在", "到", "查", "问", "搜"):
            if candidate.startswith(prefix) and len(candidate) > len(prefix) + 1:
                candidate = candidate[len(prefix):]
        # Filter filler tokens / too-short candidates.
        if len(candidate) < 2:
            return ""
        if candidate in ("当地", "本地", "这里", "我这", "我们这"):
            return ""
        if any(bad in candidate for bad in ["我", "说", "问", "晚上", "今晚", "今天", "明天"]):
            return ""
        return candidate

    def _get_running_music_app(self) -> str | None:
        """检测正在运行的音乐应用"""
        # 常见音乐应用列表（按优先级排序）
        music_apps = [
            ("NeteaseMusic", "网易云音乐"),
            ("Spotify", "Spotify"),
            ("Music", "Apple Music"),
            ("QQMusic", "QQ音乐"),
            ("Kugou", "酷狗音乐"),
            ("VLC", "VLC"),
        ]
        
        for app_name, _ in music_apps:
            try:
                result = subprocess.run(
                    ["pgrep", "-x", app_name], 
                    capture_output=True, 
                    timeout=1
                )
                if result.returncode == 0:
                    return app_name
            except Exception:
                continue
        return None

    def _media_control(self, action: str, preferred_apps: list[str]) -> str:
        """
        智能媒体控制：
        1. 如果有正在运行的播放器 -> 控制它
        2. 如果是播放命令且没有播放器 -> 打开默认播放器并播放
        3. 优先使用系统媒体键
        """
        # 检测正在运行的播放器
        running_app = self._get_running_music_app()
        
        # 如果是 "播放" 命令且没有播放器运行 -> 打开默认播放器
        if action in ["play", "playpause"] and not running_app:
            # 优先使用用户偏好的 app，否则用 Apple Music
            default_app = preferred_apps[0] if preferred_apps else "Music"
            print(f"🎵 No music app running, opening {default_app}...")
            try:
                from core.tools_impl import open_app
                _ = open_app(default_app)
            except Exception:
                try:
                    subprocess.run(["open", "-a", default_app], check=False)
                except Exception:
                    pass
            import time
            time.sleep(1)  # 等待 app 启动
        
        # 使用系统媒体键控制（适用于所有播放器）
        result = self._send_system_media_key(action)
        if result:
            return result
        
        # 回退：尝试 AppleScript 直接控制特定 app
        command_map = {
            "playpause": "playpause",
            "play": "play",
            "pause": "pause",
            "next": "next track",
            "previous": "previous track",
        }
        osascript_cmd = command_map.get(action, "playpause")
        
        # 构建候选列表：运行中的 app > 用户偏好 > 默认
        app_candidates = []
        if running_app:
            app_candidates.append(running_app)
        app_candidates.extend(preferred_apps)
        app_candidates.extend(["Music", "Spotify"])
        
        for app in app_candidates:
            script = f'tell application "{app}" to {osascript_cmd}'
            try:
                subprocess.run(["osascript", "-e", script], check=True)
                return f"已控制 {app} 播放 {action}"
            except Exception:
                continue
        return "未找到可控制的播放器"

    def _send_system_media_key(self, action: str) -> str:
        """
        使用 macOS 系统级媒体键事件，适用于任意播放器（网易云、Spotify、Music 等）
        通过 Quartz 框架发送 NX_KEYTYPE 事件
        """
        # macOS 媒体键 key code (NX_KEYTYPE_*)
        # NX_KEYTYPE_PLAY = 16, NX_KEYTYPE_NEXT = 17, NX_KEYTYPE_PREVIOUS = 18
        keytype_map = {
            "playpause": 16,  # NX_KEYTYPE_PLAY
            "play": 16,
            "pause": 16,
            "next": 17,       # NX_KEYTYPE_NEXT
            "previous": 18,   # NX_KEYTYPE_PREVIOUS
        }
        keytype = keytype_map.get(action)
        if keytype is None:
            return ""
        
        # 使用 Python Quartz 绑定发送媒体键事件
        try:
            import Quartz  # type: ignore[import-not-found]
            
            def send_media_key(key):
                # Key down
                ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(  # type: ignore[attr-defined]
                    Quartz.NSEventTypeSystemDefined,  # type: ignore[attr-defined]  # 14
                    (0, 0),
                    0xa00,  # NX_KEYDOWN << 8
                    0,
                    0,
                    0,
                    8,  # NX_SUBTYPE_AUX_CONTROL_BUTTONS
                    (key << 16) | (0xa << 8),  # key << 16 | NX_KEYDOWN << 8
                    -1
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())  # type: ignore[attr-defined]
                
                # Key up
                ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(  # type: ignore[attr-defined]
                    Quartz.NSEventTypeSystemDefined,  # type: ignore[attr-defined]
                    (0, 0),
                    0xb00,  # NX_KEYUP << 8
                    0,
                    0,
                    0,
                    8,
                    (key << 16) | (0xb << 8),  # key << 16 | NX_KEYUP << 8
                    -1
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())  # type: ignore[attr-defined]
            
            send_media_key(keytype)
            action_name = {"playpause": "播放/暂停", "play": "播放", "pause": "暂停", "next": "下一曲", "previous": "上一曲"}
            return f"{action_name.get(action, action)} 🎵"
        except ImportError:
            # Quartz 未安装，回退到 osascript 方式
            return ""
        except Exception as e:
            print(f"Media key error: {e}")
            return ""

    def _filter_chat_text(self, text: str):
        if not text:
            return text
        blocked_words = ["neutral", "happy", "sad", "angry", "fear", "surprised"]
        blocked_phrases = [
            "AIspeak",
            "cant be",
            "AIspeak cant be",
            "<system-reminder>",
            "system-reminder",
            "<|system|>",
            "<|user|>",
            "<|assistant|>",
            "<|im_start|>",
            "<|im_end|>",
            "系统提示",
            "提示词",
            "文件工具哒",
            "工具哒",
        ]
        for word in blocked_words:
            text = text.replace(word, "")
        for phrase in blocked_phrases:
            text = text.replace(phrase, "")
        allowed_emoji = {"✨", "😤", "💖"}
        allowed_punct = set("，。！？!?、,.~:：;；()（）[]【】" )
        output = []
        for ch in text:
            code = ord(ch)
            if ch in allowed_emoji:
                output.append(ch)
                continue
            if ch in allowed_punct:
                output.append(ch)
                continue
            if ch.isalnum() or ch.isspace():
                output.append(ch)
                continue
            if 0x4E00 <= code <= 0x9FFF:
                output.append(ch)
                continue
        return "".join(output)

    def _short_care_phrase(self):
        phrases = [
            "我在这儿陪你哒💖",
            "别担心，我在呢哒😤",
            "我会一直陪你哒✨",
            "有我在就别怕哒💖",
            "我会听你说哒😤",
            "我一直在等你哒✨",
            "我陪你慢慢来哒💖",
            "先深呼吸一下哒😤",
        ]
        return random.choice(phrases)

    def _collapse_repeats(self, text: str):
        if not text:
            return text
        output = []
        last_char = None
        repeat_count = 0
        for ch in text:
            if ch == last_char:
                repeat_count += 1
            else:
                repeat_count = 0
            last_char = ch
            if repeat_count < 2:
                output.append(ch)
        return "".join(output)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global kage_server
    mode = os.environ.get("KAGE_MODE", "runtime").strip().lower()
    if not kage_server:
        if mode == "control":
            # In control mode, do not auto-init heavy runtime. Wait for /api/runtime/start.
            await websocket.accept()
            await websocket.send_json({"type": "state", "state": "BOOTING"})

            timeout_sec = 90
            start = time.time()
            while kage_server is None and (time.time() - start) < timeout_sec:
                await asyncio.sleep(0.2)

            if kage_server is None:
                await websocket.send_json({"type": "state", "state": "ERROR", "error": "runtime start timeout"})
                await websocket.close()
                return
        else:
            # Fallback if accessed via direct uvicorn without lifespan
            print("⚠️ Lazy Init triggered via Websocket (Fallback)")
            kage_server = KageServer(config=_load_effective_config())

    await kage_server.connect(websocket)
    try:
        kage_server.ensure_main_loop_started()
        while True:
            raw = await websocket.receive_text()
            # Handle text_input messages from CLI / frontend
            try:
                msg = json.loads(raw)
                if msg.get("type") == "text_input" and msg.get("text", "").strip():
                    if kage_server.audio_orchestrator.should_interrupt_for_text_input(getattr(kage_server, "_ui_state", "")):
                        try:
                            await kage_server.interrupt_speech(reason="text_input")
                        except Exception:
                            pass
                    if hasattr(kage_server, "_text_input_queue"):
                        incoming_turn_id = str(msg.get("turn_id") or "").strip()
                        if not incoming_turn_id:
                            incoming_turn_id = f"ws-{uuid4().hex[:8]}"
                        await kage_server._text_input_queue.put((incoming_turn_id, msg["text"].strip()))
            except (json.JSONDecodeError, Exception):
                pass
    except WebSocketDisconnect:
        await kage_server.disconnect()
    except Exception as e:
        print(f"WebSocket Error: {e}")
        try:
            await kage_server.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=12345)

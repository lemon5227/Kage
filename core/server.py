# pyright: reportGeneralTypeIssues=false
import asyncio
import json
import logging
import traceback
import random
import time
import re
import threading
import subprocess
import hashlib
import sys
import datetime
import os
import shutil
import uvicorn
import urllib.request
import urllib.error
from uuid import uuid4
from urllib.parse import quote
from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
from core.avatar_animation import AvatarAnimation
from core.audio_orchestrator import AudioOrchestrator
from core.background_lane import BackgroundLane
from core.background_worker import BackgroundWorker
from core.dialog_state_machine import DialogStateMachine
from core.interaction_state import (
    PendingVideoFollowup,
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
from core.response_sanitizer import sanitize_for_speech_text
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
)
from core.media_controller import media_control as _media_control_engine
from core.speech_engine import mouth_speak as _mouth_speak_engine
from core.route_classifier import (
    is_route_ambiguous,
    classify_route_by_model,
)
from core.chat_polisher import (
    polish_chat_response,
    infer_chat_topic,
    structured_chat_followup,
)
from core.trace import log
from core.weather_service import (
    WeatherService,
    fetch_open_meteo,
    fetch_metno,
    fetch_wttr,
    fetch_wttr_j1,
    resolve_coords,
    normalize_city_for_weather,
)

logger = logging.getLogger(__name__)


# Precompiled regex for _extract_city stopword removal.
# Sorted by length descending so longer phrases match before shorter substrings.
_CITY_STOPWORDS = [
    "天气", "怎么样", "如何", "今天", "现在", "查询", "查", "一下", "看看", "帮我",
    "的", "吗", "么", "呀", "啊", "呢", "是不是", "想", "告诉我",
    "我说", "我想", "我问", "我", "说", "问",
    "晚上", "今晚上", "今晚", "明天", "后天", "上午", "下午", "早上", "中午",
    "嗯", "嗯嗯", "额", "呃", "唉", "em",
    "当地", "本地", "这里", "我这", "我们这",
    "所以", "那", "然后", "不过", "就是", "此刻",
    "去", "去查", "去看看", "去问", "帮我查", "帮我问",
    "网络", "网上", "搜索", "搜", "搜下", "搜一下", "网络搜", "网络查询", "网络搜一下",
]
_CITY_STOPWORDS_RE = re.compile(
    "|".join(re.escape(w) for w in sorted(set(_CITY_STOPWORDS), key=len, reverse=True))
)
_CITY_TOKEN_RE = re.compile(r"[A-Za-z\u4e00-\u9fff]+")

# Location correction patterns for _quick_chat_response (called every text turn)
_RE_LOCATION_CORRECTION = re.compile(
    r"我不在([A-Za-z\u4e00-\u9fff]{2,})\s*.*我在([A-Za-z\u4e00-\u9fff]{2,})"
)
_RE_LOCATION_SET = re.compile(r"我(?:现在)?在\s*([A-Za-z\u4e00-\u9fff]{2,})")

# Fast-path cache bounds (per-query keys can grow unbounded otherwise).
_FAST_CACHE_MAX = 256
_FAST_CACHE_STALE_SEC = 600  # entries older than this get pruned first
_FAST_CACHE_MODULE_LOCK = threading.Lock()


class _FastCacheAdapter:
    """Adapter bridging KageServer._fast_cache to weather_service CacheProtocol."""

    def __init__(self, server: Any):
        self._server = server

    def get(self, key: str, ttl: int) -> str | None:
        val = self._server._get_fast_cache(key, ttl=ttl)
        return str(val) if val else None

    def set(self, key: str, value: str) -> None:
        self._server._set_fast_cache(key, value)



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

    # Hybrid (local-with-cloud-fallback) mode. Disabled by default — when the
    # user opts in we additionally require a cloud_api.api_key before the
    # broker actually wraps providers. Pure-local default is preserved.
    hybrid_cfg = dict(model_cfg.get("hybrid") or {})
    hybrid_defaults = {
        "enabled": False,
        "escalate_keywords": [],
    }
    hybrid_cfg = _deep_merge(hybrid_defaults, hybrid_cfg)

    # Cloud provider config. provider_type=="anthropic" routes through the
    # native Anthropic Messages API; otherwise the OpenAI-compatible layer
    # (also covers DeepSeek, Moonshot, Together, Groq, etc.).
    cloud_cfg = dict(model_cfg.get("cloud_api") or {})
    cloud_defaults = {
        "provider_type": "openai",
        "api_key": "",
        "model_name": "",
        "base_url": "",
        "timeout_sec": 120,
    }
    cloud_cfg = _deep_merge(cloud_defaults, cloud_cfg)
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
    model_cfg["hybrid"] = hybrid_cfg
    model_cfg["cloud_api"] = cloud_cfg
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
        logger.info("Lifespan Startup: control mode (skip heavy init)")
    else:
        if kage_server is None:
            logger.info("Lifespan Startup: initializing KageServer...")
            kage_server = KageServer(config=_load_effective_config())
        # Optionally auto-start the main loop (mic / wakeword) even without a
        # websocket client connected.
        autostart_env = str(os.environ.get("KAGE_AUTOSTART", "")).strip().lower()
        always_listen_env = str(os.environ.get("KAGE_ALWAYS_LISTEN", "")).strip().lower()
        if autostart_env in ("1", "true", "yes", "on") or always_listen_env in ("1", "true", "yes", "on"):
            try:
                kage_server.ensure_main_loop_started()
                logger.info("Main loop autostart enabled")
            except Exception as e:
                logger.warning("Failed to autostart main loop: %s", e, exc_info=True)
    try:
        yield
    finally:
        from core.routes.browser_tasks import close_service
        await close_service()
        if kage_server:
            kage_server.is_running = False
            try:
                await kage_server.background_worker.stop()
            except Exception as exc:
                logger.warning("background_worker.stop() failed during shutdown: %s", exc)
            # Flush pending memory facts before exit
            try:
                if hasattr(kage_server, "agentic_loop") and kage_server.agentic_loop:
                    kage_server.agentic_loop.flush_pending_facts()
            except Exception as exc:
                logger.warning("flush_pending_facts() failed during shutdown: %s", exc)
            logger.info("Lifespan Shutdown: stopping KageServer...")

app = FastAPI(lifespan=lifespan)

# Enable CORS — restrict to Tauri and local dev origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",   # Tauri dev
        "http://localhost:5173",   # Vite dev
        "http://localhost:5174",   # Vite dev (alternate)
        "tauri://localhost",       # Tauri production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


_local_runtime = LocalModelRuntime(
    user_dir=_get_user_dir(),
    managed_model_getter=_get_managed_model,
)


def _get_kage_server():
    """Get the running KageServer instance."""
    return kage_server


# --- Mount Modular API Routers ---
from core.routes.system import router as system_router
from core.routes.models import router as models_router
from core.routes.memory import router as memory_router
from core.routes.browser_tasks import router as browser_tasks_router

app.include_router(system_router)
app.include_router(models_router)
app.include_router(memory_router)
app.include_router(browser_tasks_router)

# Re-exports for backward compatibility
from core.routes.system import (
    health,
    get_config,
    set_config,
    runtime_status,
    runtime_start,
    get_hybrid_settings,
    detect_provider_credentials_endpoint,
    update_hybrid_settings,
    test_provider_endpoint,
)
from core.routes.models import (
    list_model_downloads,
    get_model_download,
    start_model_download,
    list_models,
    delete_model,
    llama_status,
    llama_start,
    llama_stop,
    activate_model,
)
from core.routes.memory import (
    memory_stats,
    memory_entries,
    memory_deduplicate,
    memory_merge,
    memory_profile,
    memory_profile_history,
    memory_profile_restore,
    memory_forget,
    memory_delete_entry,
)


class KageServer:
    def __init__(self, config: dict | None = None):
        logger.info("Initializing Kage Server (Heavy Load)...")

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
        logger.info("Loading identity store...")
        self.identity_store = IdentityStore()
        self.identity_store.ensure_files_exist()

        logger.info("Loading memory...")
        self.memory = MemorySystem()
        # Warm up vector model asynchronously to avoid blocking startup
        def _warmup():
            self.memory.warmup_model()
        threading.Thread(target=_warmup, daemon=True, name="memory-warmup").start()
        logger.info("Vector search model warming up in background...")

        # --- Session persistence ---
        logger.info("Loading session manager...")
        self.session_manager = SessionManager()
        self.session_manager.load_from_file()

        self.model_broker = ModelBroker(cfg)
        realtime_profile = self.model_broker.profile("realtime")
        background_profile = self.model_broker.profile("background")

        logger.info("Realtime model provider: %s (%s)", realtime_profile.mode, realtime_profile.name)
        logger.info("Background model provider: %s (%s)", background_profile.mode, background_profile.name)

        if self._text_only_mode:
            logger.info("Text-only mode enabled: skip TTS/ASR init")
            self.mouth = None
            self.ears = None
        else:
            logger.info("Initializing TTS voice: %s", voice)
            self.mouth = KageMouth(voice=voice)

            logger.info("Loading ASR models...")
            self.ears = KageEars(model_id="paraformer-zh")

        # --- Tool Registry ---
        logger.info("Loading tool registry...")
        self.tool_registry = create_default_registry(memory_system=self.memory)
        # NOTE: Runtime uses unified ToolRegistry + ToolExecutor + AgenticLoop.
        # Keep runtime tool surface small and deterministic.
        self.tools = None

        # --- Tool Executor (使用新的 Tool_Registry) ---
        self.tool_executor = ToolExecutor(tool_registry=self.tool_registry)

        # --- Model Providers by role ---
        self.routing_model_provider = self.model_broker.routing_provider
        self.realtime_model_provider = self.model_broker.realtime_provider
        self.background_model_provider = self.model_broker.background_provider
        self.model_provider = self.background_model_provider
        self.fallback_model_provider = self.model_broker.fallback_provider

        # --- Prompt Builder (使用新的 Tool_Registry) ---
        from core.memory_profile import MemoryProfile
        memory_profile = MemoryProfile(identity_store=self.identity_store)
        self.identity_store.set_memory_profile(memory_profile)

        self.prompt_builder = PromptBuilder(
            identity_store=self.identity_store,
            memory_system=self.memory,
            tool_registry=self.tool_registry,
            memory_cfg=cfg.get("memory", {}) if isinstance(cfg.get("memory", {}), dict) else {},
            prune_tools=True,
            memory_profile=memory_profile,
        )

        # --- Agentic Loop ---
        self.agentic_loop = AgenticLoop(
            model_provider=self.model_provider,
            tool_executor=self.tool_executor,
            prompt_builder=self.prompt_builder,
            session_manager=self.session_manager,
            memory_system=self.memory,
            memory_profile=memory_profile,
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

        # Short-lived interactive dialog state unified with SessionManager
        self.session = self.session_manager
        self.dialog_state = DialogStateMachine(self.session)
        self.background_lane = BackgroundLane()
        self.audio_orchestrator = AudioOrchestrator(
            wakeword_enabled_cfg=self._wakeword_enabled_cfg,
        )
        self.background_agentic_loop = self.agentic_loop.create_isolated_runner(
            model_provider=self.background_model_provider,
        )
        self.background_worker = BackgroundWorker(
            lane=self.background_lane,
            processor=self._process_background_job,
            on_event=self._notify_job_event,
            context_factory=lambda: self.agentic_loop.create_isolated_runner(
                model_provider=self.background_model_provider,
            ),
        )
        
        self.active_websocket: WebSocket | None = None
        self.is_running = True
        self._main_loop_task: asyncio.Task | None = None
        self._ui_state = "IDLE"
        self._speech_revision = 0
        # Live2D animation config (extracted to independent module)
        self.avatar_animation = AvatarAnimation()
        self._last_motion_time = 0.0  # kept for backward compat during transition
        self._fast_cache = {}
        self._fast_cache_lock = threading.Lock()
        self._weather_service = WeatherService(cache=_FastCacheAdapter(self))
        self._text_input_queue: asyncio.Queue = asyncio.Queue()
        self._active_turn_id: str | None = None
        threading.Thread(target=self._prefetch_local_city, daemon=True).start()
        logger.info("Kage Server Ready!")

    @property
    def weather_service(self) -> WeatherService:
        ws = getattr(self, "_weather_service", None)
        if ws is None:
            ws = WeatherService(cache=_FastCacheAdapter(self))
            self._weather_service = ws
        return ws

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
        logger.info("Client connected!")
        await self.send_state("IDLE")

    async def disconnect(self):
        self.active_websocket = None
        logger.info("Client disconnected")

    def reload_model_broker(self) -> None:
        """Rebuild ModelBroker from the latest on-disk config and update
        every cached provider reference so the next turn uses the new
        settings — no process restart needed.

        Safe to call from a settings-save handler. Failure is loud (we
        re-raise) so the caller can report `reload: failed: ...` to the UI.
        """
        cfg = _load_effective_config()
        broker = ModelBroker(cfg)

        # Replace the broker first so any code paths that grab providers
        # via `self.model_broker.foo_provider` see the new ones immediately.
        self.model_broker = broker
        self.routing_model_provider = broker.routing_provider
        self.realtime_model_provider = broker.realtime_provider
        self.background_model_provider = broker.background_provider
        self.model_provider = self.background_model_provider
        self.fallback_model_provider = broker.fallback_provider

        # AgenticLoop holds its own ref. Update it so the next run() call
        # uses the new provider — otherwise the loop would keep using the
        # provider captured at __init__ time.
        agentic = getattr(self, "agentic_loop", None)
        if agentic is not None:
            agentic.model = self.background_model_provider

        logger.info(
            "ModelBroker reloaded — modes: routing=%s realtime=%s background=%s fallback=%s",
            self.model_broker.profile("routing").mode,
            self.model_broker.profile("realtime").mode,
            self.model_broker.profile("background").mode,
            self.model_broker.profile("fallback_cloud").mode,
        )

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
            except Exception:
                logger.warning("Send Error: %s", exc_info=True)

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

    def _record_turn_completed(self, user_input: str, assistant_response: str) -> None:
        """Record completed turn to both in-memory and file-backed session state."""
        u = str(user_input or "").strip()
        a = str(assistant_response or "").strip()
        if not u or not a:
            return
        if hasattr(self, "session") and self.session is not None:
            try:
                self.session.add_turn("user", u)
                self.session.add_turn("assistant", a)
            except Exception:
                pass
        if hasattr(self, "session_manager") and self.session_manager is not None and self.session_manager is not getattr(self, "session", None):
            try:
                self.session_manager.add_turn("user", u)
                self.session_manager.add_turn("assistant", a)
            except Exception:
                pass

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
        allowed = ("completed", "failed", "stopped") if job.get('task_type') == 'browser_experiment' else ("completed", "failed")
        if str(event or "") not in allowed:
            return False
        if not bool(job.get("notify_on_finish", True)):
            return False
        if self.active_websocket is None:
            return False
        return str(self._ui_state or "IDLE") == "IDLE"

    def _background_completion_notification(self, event: str, job: dict[str, Any]) -> str:
        if not self._should_notify_background_completion(event, job):
            return ""
        if job.get('task_type') == 'browser_experiment':
            result = job.get('result') if isinstance(job.get('result'), dict) else {}
            status = result.get('task_status') or job.get('status')
            messages = {
                'completed': '浏览器实验检查通过了。',
                'failed': '浏览器实验未通过检查。',
                'unknown': '浏览器实验已结束，结果待确认。',
                'stopped': '浏览器实验已停止。',
            }
            return messages.get(status, '浏览器实验已结束，结果待确认。')
        label = self._background_task_label(str(job.get("task_type") or ""))
        if str(event or "") == "completed":
            return f"{label}完成了。你想听结果的话，我现在就可以继续说。"
        return f"{label}失败了。你要我重试的话，就直接告诉我。"

    async def _process_background_job(self, job: dict[str, Any], context: Any = None) -> dict[str, Any]:
        runner = context or getattr(self, "background_agentic_loop", self.agentic_loop)
        loop_result = await runner.run(
            user_input=str(job.get("input_text") or ""),
            current_emotion="neutral",
        )
        return {
            "final_text": str(loop_result.final_text or "").strip(),
            "tool_calls_executed": len(loop_result.tool_calls_executed or []),
        }

    async def run_loop(self):
        """The Main Async Event Loop"""
        logger.info("Starting Main Loop...")
        
        # Start heartbeat if enabled
        if self._heartbeat_enabled:
            try:
                await self.heartbeat.start()
                logger.info("Heartbeat started")
            except Exception:
                logger.warning("Heartbeat start failed: %s", exc_info=True)

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
                            self._record_turn_completed(user_input, early_action.speech)
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
                    ack_text = self._background_ack_text(realtime_task.reason)
                    await self.mouth_speak(ack_text, current_emotion_str)
                    self._record_turn_completed(user_input, ack_text)
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
                    self._record_turn_completed(user_input, reply)
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
                    confirm_prompt = f"我理解你想{intent_desc}。确认就说‘确认’，如果不是这个就说‘不是这个，是…’。"
                    await self.mouth_speak(
                        confirm_prompt,
                        current_emotion_str,
                    )
                    self._record_turn_completed(user_input, confirm_prompt)
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
                        self._record_turn_completed(user_input, str(cached_video))
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
                                no_match_msg = f"我暂时没在结果里命中“{subject}”这个博主名（检索耗时约{video_search_ms / 1000:.1f}秒）。你可以说‘不是这个，是完整博主名’让我重试。"
                                await self.mouth_speak(
                                    no_match_msg,
                                    current_emotion_str,
                                )
                                self._record_turn_completed(user_input, no_match_msg)
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
                            self._record_turn_completed(user_input, video_reply)
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
                            title_reply = f"我找到一个最新视频候选：{title}。"
                            await self.mouth_speak(title_reply, current_emotion_str)
                            self._record_turn_completed(user_input, title_reply)
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
                            self._record_turn_completed(user_input, reply)
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
                    self._record_turn_completed(user_input, reply)
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
                        infer_chat_topic=infer_chat_topic,
                        structured_chat_followup=structured_chat_followup,
                        polish_chat_response=polish_chat_response,
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
                                self._record_turn_completed(user_input, str(final_speech))
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
                        self._record_turn_completed(user_input, final_speech)
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
                    confirm_prompt = f"要执行删除类操作：{preview}\n确认吗？回复‘确认’或‘取消’。"
                    await self.mouth_speak(confirm_prompt, current_emotion_str)
                    self._record_turn_completed(user_input, confirm_prompt)
                    self._log_turn_done(path="need_confirmation", route=route_hint, elapsed_ms=_turn_elapsed_ms())
                    continue

                # NOTE: legacy chat post-processing removed in unified loop.

                print(f"👻 Kage: {final_speech}")
                await self.mouth_speak(final_speech, current_emotion_str)
                self._record_turn_completed(user_input, str(final_speech))
                self._log_turn_done(path="agentic_loop", route=route_hint, elapsed_ms=_turn_elapsed_ms())

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
            resp = self.realtime_model_provider.generate(
                messages=messages,
                tools=None,
                max_tokens=200,
                temperature=0.7,
            )
            return [str(getattr(resp, "text", "") or "")]
        except Exception as exc:
            return [f"模型调用失败: {exc}"]

    # NOTE: Legacy tool-loop/router removed. The runtime uses AgenticLoop + ToolExecutor.

    async def mouth_speak(self, text, emotion="neutral"):
        """Delegate to speech_engine module."""
        await _mouth_speak_engine(self, text, emotion)

    def _sanitize_for_speech(self, text: str) -> str:
        """Delegate to response_sanitizer.

        Kept as a thin wrapper to support tests that exercise the
        sanitization pipeline through the server instance.
        """
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
        if not is_route_ambiguous(str(user_input or ""), base):
            return base

        try:
            assisted = classify_route_by_model(str(user_input or ""), self.routing_model_provider)
            if assisted in ("command", "info", "chat"):
                log("server", "route.assist", base=base, assisted=assisted)
                return assisted
        except Exception:
            pass
        return base

    def _classify_route_by_model(self, user_input: str) -> str:
        """Use lightweight model call for ambiguous route classification."""
        return classify_route_by_model(user_input, self.routing_model_provider)

    def _fetch_weather_tool_call_quick(self, city: str) -> dict | None:
        """Fetch wttr JSON quickly and convert to tool-call-like payload."""
        try:
            data = fetch_wttr_j1(str(city or "Shanghai"))
            if not isinstance(data, dict):
                return None
            payload = {"success": True, "content": json.dumps(data, ensure_ascii=False)}
            return {"name": "web_fetch", "success": True, "result": json.dumps(payload, ensure_ascii=False)}
        except Exception:
            return None

    def _quick_chat_response(self, user_input: str):
        text = (user_input or "").strip()
        if not text:
            return None

        # Location correction (used by local weather queries)
        try:
            # "我不在巴黎 我在尼斯"
            m = _RE_LOCATION_CORRECTION.search(text)
            if m:
                city = m.group(2)
                self._set_location_override(city)
                return f"好，我记下了，你在{city}。"
            # "我在尼斯" / "我现在在尼斯"
            m = _RE_LOCATION_SET.search(text)
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

    def _call_tool(self, tool_name: str, *args, **kwargs):
        """Unified tool call with fallback to direct import."""
        tools = getattr(self, "tools", None)
        if tools is not None and hasattr(tools, tool_name):
            try:
                return getattr(tools, tool_name)(*args, **kwargs)
            except Exception as exc:
                log("tool", "fallback", tool=tool_name, error=str(exc))
        try:
            import core.tools_impl as tools_impl
            return getattr(tools_impl, tool_name)(*args, **kwargs)
        except (AttributeError, Exception) as exc:
            log("tool", "call_failed", tool=tool_name, error=str(exc))
            return None

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
            return self._call_tool("smart_search", q, max_results=3)

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
            return self._call_tool("system_control", "brightness", action)

        # 独立的静音命令
        if "静音" in text or "mute" in lower_text:
            action = "unmute" if "取消" in text or "un" in lower_text else "mute"
            print("🧭 Direct: system_control -> mute")
            return self._call_tool("system_control", "volume", action)

        if "音量" in text or "声音" in text:
            action = "up"
            if any(token in text for token in ["小", "低", "降低", "调低"]):
                action = "down"
            print("🧭 Direct: system_control -> volume")
            return self._call_tool("system_control", "volume", action)

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
            return self._call_tool("system_control", "bluetooth", action)

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
            return self._call_tool("system_control", "wifi", action)


        # 网站/应用打开交给大模型 action tool-calls，以获得更好的泛化能力。

        # 网站快捷打开 - 必须是"打开"而非"关闭"
        is_open_action = "打开" in text or "open" in lower_text
        is_close_action = "关闭" in text or "close" in lower_text or "退出" in text

        # 关闭应用快速路径
        if is_close_action and not is_open_action:
            close_match = re.search(r"(?:关闭|退出|关掉)(.+)", text)
            if close_match:
                target = close_match.group(1).strip(" ：:，,。\n\t吧请")
                # 网站 -> 关闭浏览器
                if any(site in target for site in ["b站", "哔哩哔哩", "知乎", "百度", "网页", "浏览器"]):
                    print("🧭 Direct: close_app -> Safari (网页)")
                    return self._call_tool("system_control", "app", "close", "Safari")
                # 其他应用
                if target:
                    print(f"🧭 Direct: close_app -> {target}")
                    return self._call_tool("system_control", "app", "close", target)

        if "几点" in text or "时间" in text:
            print("🧭 Direct: get_time")
            result = self._call_tool("get_time")
            return self._persona_wrap(result, "time") if result else None

        if "截图" in text or "截屏" in text:
            print("🧭 Direct: take_screenshot")
            result = self._call_tool("take_screenshot")
            return self._persona_wrap(result, "screenshot") if result else None

        if "电量" in text or "电池" in text:
            print("🧭 Direct: battery_status")
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

    def _get_local_city(self) -> str:
        return self.weather_service.get_local_city()

    async def _get_local_city_async(self) -> str:
        return await asyncio.to_thread(self._get_local_city)

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
        """Open-Meteo provider (delegated to weather_service)."""
        return fetch_open_meteo(city, day_offset=day_offset, cache=_FastCacheAdapter(self))

    def _fetch_weather_metno(self, city: str) -> str:
        """MET Norway provider (delegated to weather_service)."""
        return fetch_metno(city, cache=_FastCacheAdapter(self))

    def _resolve_weather_coords(self, city: str) -> tuple[float, float, str] | None:
        """Resolve city to coordinates (delegated to weather_service)."""
        return resolve_coords(city, cache=_FastCacheAdapter(self))

    def _prefetch_local_city(self):
        try:
            self._get_local_city()
        except Exception:
            pass

    def _get_fast_cache(self, key: str, ttl: int):
        lock = getattr(self, "_fast_cache_lock", _FAST_CACHE_MODULE_LOCK)
        with lock:
            entry = self._fast_cache.get(key)
            if not entry:
                return ""
            if time.time() - entry["timestamp"] > ttl:
                self._fast_cache.pop(key, None)
                return ""
            return entry["value"]

    def _set_fast_cache(self, key: str, value: str):
        lock = getattr(self, "_fast_cache_lock", _FAST_CACHE_MODULE_LOCK)
        with lock:
            if len(self._fast_cache) >= _FAST_CACHE_MAX:
                now = time.time()
                items = list(self._fast_cache.items())
                stale = [k for k, v in items if now - v["timestamp"] > _FAST_CACHE_STALE_SEC]
                for k in stale:
                    self._fast_cache.pop(k, None)
                if len(self._fast_cache) >= _FAST_CACHE_MAX:
                    ordered = sorted(list(self._fast_cache.items()), key=lambda kv: kv[1]["timestamp"])
                    for k, _ in ordered[: len(ordered) // 4]:
                        self._fast_cache.pop(k, None)
            self._fast_cache[key] = {"timestamp": time.time(), "value": value}

    def _fetch_weather(self, city: str) -> str:
        return self.weather_service.get_weather(city)

    async def _fetch_weather_async(self, city: str) -> str:
        return await asyncio.to_thread(self._fetch_weather, city)

    def _extract_city(self, text: str) -> str:
        # If the user already corrected location, prefer that mention.
        try:
            override = self._get_fast_cache("location_override", ttl=86400)
            if override and str(override) in text:
                return str(override)
        except Exception:
            pass

        cleaned = text
        # Single-pass regex replacement instead of 50+ string.replace() calls.
        # The regex was built with stopwords sorted by length descending, so longer
        # phrases match before their substring fragments.
        cleaned = _CITY_STOPWORDS_RE.sub("", cleaned)
        cleaned = cleaned.strip(" ：:，,。\n\t")
        if not cleaned:
            return ""
        matches = _CITY_TOKEN_RE.findall(cleaned)
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
        if any(bad in candidate for bad in ("我", "说", "问", "晚上", "今晚", "今天", "明天")):
            return ""
        return candidate

    def _media_control(self, action: str, preferred_apps: list[str]) -> str:
        """Delegate to media_controller module."""
        return _media_control_engine(action, preferred_apps)


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

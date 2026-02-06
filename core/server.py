# pyright: reportGeneralTypeIssues=false
import asyncio
import json
import traceback
import random
import time
import re
import threading
import subprocess
from urllib.parse import quote
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
import shutil
import uvicorn
from uuid import uuid4
from typing import Any

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


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_effective_config() -> dict:
    repo_cfg = _load_json(os.path.join(parent_dir, "config", "settings.json"))
    user_cfg = _load_json(_get_user_config_path())
    return _deep_merge(repo_cfg, user_cfg)


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
    yield
    # Shutdown
    if kage_server:
        kage_server.is_running = False
        print("🛑 Lifespan Shutdown: stopping KageServer...")

app = FastAPI(lifespan=lifespan)


# --- Model Download Jobs (Control Plane) ---
_download_lock = threading.Lock()
_download_jobs: dict[str, dict] = {}


def _find_active_download_job(repo_id: str, revision: str | None = None) -> str | None:
    """Return an existing job_id if the same repo is already downloading."""
    with _download_lock:
        for job_id, job in _download_jobs.items():
            try:
                if job.get("repo_id") != repo_id:
                    continue
                if revision is not None and job.get("revision") not in (None, revision):
                    continue
                if job.get("status") in ("queued", "running"):
                    return str(job_id)
            except Exception:
                continue
    return None


def _set_job(job_id: str, patch: dict):
    with _download_lock:
        job = _download_jobs.get(job_id)
        if not job:
            return
        job.update(patch)


def _get_job(job_id: str) -> dict | None:
    with _download_lock:
        job = _download_jobs.get(job_id)
        return dict(job) if job else None


def _list_jobs() -> list[dict]:
    with _download_lock:
        return [dict(v) for v in _download_jobs.values()]


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
    if not repo_id:
        return {"error": "repo_id required"}

    # De-dupe: if the same repo is already downloading, return that job.
    existing = _find_active_download_job(repo_id, revision=revision if isinstance(revision, str) else None)
    if existing:
        return {"job_id": existing, "status": "already_running"}

    job_id = uuid4().hex
    now = time.time()
    with _download_lock:
        _download_jobs[job_id] = {
            "job_id": job_id,
            "repo_id": repo_id,
            "revision": revision,
            "status": "queued",
            "stage": "queued",
            "created_at": now,
            "updated_at": now,
            "current_file": None,
            "file_downloaded": 0,
            "file_total": None,
            "error": None,
        }

    def _run():
        try:
            from huggingface_hub import snapshot_download
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
                        inc = int(n) if n is not None else 0
                        cur = int(getattr(self, "n", 0) or 0)
                        _set_job(
                            job_id,
                            {
                                "file_downloaded": cur + inc,
                                "file_total": int(self.total) if self.total is not None else None,
                                "updated_at": time.time(),
                            },
                        )
                    except Exception:
                        pass
                    return super().update(n)

            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                tqdm_class=_JobTqdm,
            )
            _set_job(job_id, {"status": "completed", "stage": "completed", "updated_at": time.time()})
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
    """List downloaded MLX models in HuggingFace cache"""
    def _scan_models():
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        if not os.path.exists(cache_dir):
            return []
        
        models = []
        try:
            for item in os.listdir(cache_dir):
                if item.startswith("models--"):
                    path = os.path.join(cache_dir, item)
                    if not os.path.isdir(path):
                        continue
                        
                    size_bytes = 0
                    for root, _, files in os.walk(path):
                        for f in files:
                            size_bytes += os.path.getsize(os.path.join(root, f))
                    
                    # models--author--repo
                    parts = item.split("--")
                    readable_name = item
                    if len(parts) >= 3:
                         # Join back the repo name parts
                        author = parts[1]
                        repo = "-".join(parts[2:])
                        readable_name = f"{author}/{repo}"
                    
                    models.append({
                        "id": item,
                        "name": readable_name,
                        "size": f"{size_bytes / (1024*1024*1024):.2f} GB"
                    })
        except Exception as e:
            print(f"Error listing models: {e}")
            
        return models

    # Run in thread pool to prevent blocking main loop
    return await asyncio.to_thread(_scan_models)

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    """Delete a model from cache"""
    # Security check
    if not model_id.startswith("models--") or ".." in model_id or "/" in model_id:
        return {"error": "Invalid model ID"}
        
    def _do_delete():
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        target_path = os.path.join(cache_dir, model_id)
        
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
                return {"status": "success", "message": f"Deleted {model_id}"}
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Model not found"}

    return await asyncio.to_thread(_do_delete)

class KageServer:
    def __init__(self, config: dict | None = None):
        print("⚙️ Initializing Kage Server (Heavy Load)...")

        # Lazy imports to keep Control Plane startup fast
        from core.memory import MemorySystem
        from core.brain import KageBrain
        from core.brain_lfm import KageBrainLFM
        from core.mouth import KageMouth
        from core.ears import KageEars
        from core.tools import KageTools  # 保留用于兼容层
        from core.tool_registry import create_default_registry

        # New modules
        from core.identity_store import IdentityStore
        from core.session_manager import SessionManager
        from core.tool_executor import ToolExecutor
        from core.prompt_builder import PromptBuilder
        from core.model_provider import LocalMLXProvider, create_provider_from_settings
        from core.agentic_loop import AgenticLoop
        from core.heartbeat import Heartbeat

        cfg = config or {}
        model_path = (
            cfg.get("model", {}).get("path")
            or cfg.get("model", {}).get("default_model")
            or "mlx-community/Phi-4-mini-instruct-4bit"
        )
        voice = cfg.get("voice", {}).get("tts_voice") or "zh-CN-XiaoyiNeural"

        # --- Identity Store ---
        print("🪪 Loading identity store...", flush=True)
        self.identity_store = IdentityStore()
        self.identity_store.ensure_files_exist()

        print("🧠 Loading memory...", flush=True)
        self.memory = MemorySystem()

        # --- Session Manager (replaces SessionState) ---
        print("📝 Loading session manager...", flush=True)
        self.session_manager = SessionManager()
        self.session_manager.load_from_file()

        # 根据模型路径选择对应的 Brain 实现
        self.is_lfm_model = "LFM" in model_path or "LiquidAI" in model_path
        print(f"🧠 Loading brain model: {model_path} (LFM={self.is_lfm_model})", flush=True)
        
        if self.is_lfm_model:
            self.brain = KageBrainLFM(model_path=model_path)
        else:
            self.brain = KageBrain(model_path=model_path)

        print(f"🗣️ Initializing TTS voice: {voice}", flush=True)
        self.mouth = KageMouth(voice=voice)

        print("🎧 Loading ASR models...", flush=True)
        self.ears = KageEars(model_id="paraformer-zh")

        print("🧰 Loading tool registry...", flush=True)
        self.tool_registry = create_default_registry(memory_system=self.memory)
        self.tools = KageTools()  # 保留用于兼容层（旧代码直接调用）

        # --- Tool Executor (使用新的 Tool_Registry) ---
        self.tool_executor = ToolExecutor(tool_registry=self.tool_registry)

        # --- Model Provider ---
        self.model_provider = create_provider_from_settings(
            settings_path="config/settings.json",
            brain=self.brain,
        )

        # --- Prompt Builder (使用新的 Tool_Registry) ---
        self.prompt_builder = PromptBuilder(
            identity_store=self.identity_store,
            memory_system=self.memory,
            tool_registry=self.tool_registry,
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

        # Backward compatibility: keep old session reference
        from core.session_state import SessionState
        self.session = SessionState()
        
        self.active_websocket: WebSocket | None = None
        self.is_running = True
        self._main_loop_task: asyncio.Task | None = None
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
        print("🔌 Client connected!")
        await self.send_state("IDLE")

    async def disconnect(self):
        self.active_websocket = None
        print("🔌 Client disconnected")

    def ensure_main_loop_started(self):
        """Start the main loop once; keep it running across reconnects."""
        if self._main_loop_task is not None and not self._main_loop_task.done():
            return
        self._main_loop_task = asyncio.create_task(self.run_loop())

    async def send_message(self, type_: str, data: dict):
        if self.active_websocket:
            try:
                payload = {"type": type_, **data}
                await self.active_websocket.send_json(payload)
            except Exception as e:
                print(f"Send Error: {e}")

    async def send_state(self, state: str):
        """States: IDLE, LISTENING, THINKING, SPEAKING"""
        await self.send_message("state", {"state": state})

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
        await self.mouth_speak(greeting)

        # 会话状态
        in_conversation = False  # 是否在对话中
        
        while self.is_running:
            try:
                # --- Check for text input from WebSocket (CLI / frontend) ---
                text_from_ws = None
                try:
                    text_from_ws = self._text_input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

                if text_from_ws:
                    user_input = text_from_ws
                    voice_emotion = "neutral"
                    in_conversation = True
                    print(f"👤 [Text] Master: {user_input}")
                    await self.send_message("transcription", {"text": user_input})
                else:
                    # 检查是否需要等待唤醒词
                    if not in_conversation:
                        # 0. Wake Word Phase (待机模式)
                        # Use short timeout so we can check text_input_queue frequently
                        await self.send_state("IDLE")
                        wakeword_detected = await asyncio.to_thread(self.ears.wait_for_wakeword, 2)
                        
                        if not wakeword_detected:
                            # 超时，回到循环顶部检查文字输入队列
                            continue
                        
                        # 唤醒成功，先说话再监听 (阻塞模式，避免听到自己的声音)
                        await self.send_message("expression", {"name": "f02", "duration": 1.5})  # surprised
                        await self.mouth_speak("我在，怎么了？", "happy")
                        in_conversation = True
                        
                        # 说完后开始监听
                        await self.send_state("LISTENING")
                        listen_result = await asyncio.to_thread(self.ears.listen)
                    else:
                        # 已在对话中，直接监听
                        await self.send_state("LISTENING")
                        listen_result = await asyncio.to_thread(self.ears.listen)
                    
                    user_input = ""
                    voice_emotion = "neutral"

                    if isinstance(listen_result, tuple):
                        user_input, voice_emotion = listen_result
                    else:
                        user_input = listen_result
                    
                    if not user_input:
                        # 用户没说话：立即回到低功耗唤醒词模式，避免持续占用麦克风/录音循环
                        if in_conversation:
                            print("💤 No speech detected, returning to wake word mode")
                            in_conversation = False
                        await self.send_state("IDLE")
                        await asyncio.sleep(0.1)
                        continue
                    
                    print(f"👤 Master: {user_input}")
                    await self.send_message("transcription", {"text": user_input})

                # Determine Emotion early (needed for clarification flows)
                current_emotion: str = "neutral"
                if voice_emotion and voice_emotion != "neutral":
                    current_emotion = str(voice_emotion)
                current_emotion_str = str(current_emotion)

                # If we previously asked a clarification, consume it here.
                if self.session.pending_action and isinstance(self.session.pending_action, dict):
                    pa = self.session.pending_action
                    self.session.pending_action = None
                    if pa.get("type") == "open_app":
                        await self.send_state("THINKING")
                        # If the user meant a website, use open_website (search + open).
                        is_website = any(tok in user_input for tok in ["网站", "网页", "网址", "链接"]) or (
                            "http" in user_input.lower() or "." in user_input
                        )
                        if is_website and hasattr(self.tools, "open_website"):
                            result = await asyncio.to_thread(self.tools.open_website, user_input)
                        else:
                            result = await asyncio.to_thread(self.tools.open_app, user_input)
                        final_speech = self._persona_wrap(str(result), "app")
                        print(f"👻 Kage: {final_speech}")
                        await self.mouth_speak(final_speech, current_emotion_str)
                        continue
                    if pa.get("type") == "chat_followup":
                        # LLM 自主决策，不再使用 router.classify
                        # 直接处理 followup
                        asked = str(pa.get("asked") or "").strip()
                        topic = str(pa.get("topic") or "").strip()
                        inferred = self._infer_chat_topic(user_input)

                        # User shifted topics; treat as a new request.
                        if inferred and topic and inferred != topic:
                            pass
                        else:
                            structured = None
                            try:
                                structured = self._structured_chat_followup(topic, user_input)
                            except Exception:
                                structured = None

                            if structured:
                                final_speech = self._polish_chat_response(str(structured))
                                print(f"👻 Kage: {final_speech}")
                                await self.mouth_speak(final_speech, current_emotion_str)
                                try:
                                    self.session.add_turn("user", user_input)
                                    self.session.add_turn("assistant", str(final_speech))
                                except Exception:
                                    pass
                                continue

                            # Model followup fallback.
                            await self.send_state("THINKING")
                            try:
                                history = self.session.as_history_list()
                            except Exception:
                                history = []
                            followup_input = user_input
                            if asked:
                                followup_input = f"上一轮你问：{asked}\n用户补充：{user_input}\n请给出具体建议。"
                            response_stream = await asyncio.to_thread(  # type: ignore[arg-type]
                                self._think_action,
                                followup_input,
                                [],
                                history,
                                current_emotion_str,
                                "chat",
                            )
                            full_response = ""
                            for chunk in response_stream:
                                text = getattr(chunk, "text", str(chunk))
                                full_response += text
                            final_speech = self._polish_chat_response(full_response)
                            print(f"👻 Kage: {final_speech}")
                            await self.mouth_speak(final_speech, current_emotion_str)
                            try:
                                self.session.add_turn("user", user_input)
                                self.session.add_turn("assistant", str(final_speech))
                            except Exception:
                                pass
                            continue

                # 2. Thinking Phase
                await self.send_state("THINKING")

                # Model-first tool loop (max 3 steps)
                memories = []
                history = []
                try:
                    history = self.session.as_history_list()
                except Exception:
                    history = []
                try:
                    memories = self.memory.recall(user_input, n_result=3)
                except Exception:
                    memories = []

                final_speech, executed_tools = await self._run_tool_loop(
                    user_input=user_input,
                    memories=memories,
                    history=history,
                    current_emotion=current_emotion_str,
                    max_steps=3,
                )

                if not executed_tools:
                    # Chat post-processing
                    try:
                        polished = self._polish_chat_response(str(final_speech))
                        if polished:
                            final_speech = polished
                    except Exception:
                        pass
                    try:
                        if self._is_bad_chat_response(str(final_speech), user_input):
                            repaired = await self._repair_chat_response(
                                user_input=user_input,
                                draft=str(final_speech),
                                memories=memories,
                                history=history,
                                current_emotion=current_emotion_str,
                            )
                            if repaired and not self._is_bad_chat_response(repaired, user_input):
                                final_speech = repaired
                            else:
                                final_speech = self._fallback_chat_response(user_input)
                    except Exception:
                        pass

                print(f"👻 Kage: {final_speech}")
                await self.mouth_speak(final_speech, current_emotion_str)

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
                await asyncio.sleep(1)

    def _think_action(self, user_input: str, memories: list, history: list, current_emotion: str, mode: str):
        return self.brain.think(
            user_input=user_input,
            memories=memories,
            history=history,
            current_emotion=current_emotion,
            mode=mode,
        )

    def _think_report(self, report_input: str, current_emotion: str):
        return self.brain.think(
            user_input=report_input,
            memories=[],
            current_emotion=current_emotion,
            temp=0.7,
            mode="report",
        )

    async def _send_quick_ack(self, current_emotion: str):
        await self.mouth_speak("我马上处理~", current_emotion)

    async def _try_intent_route(self, prompt: str, current_emotion: str):
        """Lightweight keyword-based intent router.

        Returns (speech, True) if an intent was matched and executed,
        or None if no intent matched (fall through to model).

        This is intentionally simple — pattern matching on keywords,
        not hardcoded to specific names. The model is too small to
        reliably pick tools, so we route common patterns directly.
        """
        import re
        low = prompt.lower()

        # ── Intent: search + open video/channel on a platform ──
        video_kw = bool(re.search(r"视频|频道|直播", prompt))
        platform_kw = bool(re.search(r"油管|YouTube|B站|bilibili|优酷|抖音", prompt, re.IGNORECASE))

        # ── Intent: search/open video (with or without platform specified) ──
        # User says something about 视频/频道/直播 → route to search_and_open.
        # If a platform is mentioned, prefer that domain; otherwise search broadly.
        if video_kw:
            q = prompt
            for filler in ["帮我", "一下", "然后打开", "然后", "打开", "网页", "。", "，", "嗯"]:
                q = q.replace(filler, "")
            q = q.strip() or prompt

            prefer = []
            if "油管" in low or "youtube" in low:
                prefer = ["youtube.com", "youtu.be"]
            elif "b站" in low or "bilibili" in low:
                prefer = ["bilibili.com"]
            elif "优酷" in low:
                prefer = ["youku.com"]
            elif "抖音" in low:
                prefer = ["douyin.com"]

            await self._send_quick_ack(current_emotion)
            await self.send_message("speech", {"text": "", "emotion": "thinking"})
            result = await asyncio.to_thread(
                self.tools.execute_tool_call,
                "search_and_open",
                {"query": q, "prefer_domains": prefer, "max_results": 5},
            )
            speak = self._tool_result_for_speech("search_and_open", str(result))
            return speak or str(result), True

        # ── Intent: general web search + open ──
        search_trigger = bool(re.search(r"^(?:帮我)?(?:搜|查|找|搜索|搜一下|查一下|找一下)", prompt))
        has_open = "打开" in prompt or "带我去" in prompt
        if search_trigger and has_open and not video_kw:
            q = prompt
            for filler in ["帮我", "一下", "然后打开", "然后", "打开", "带我去", "。", "，", "嗯"]:
                q = q.replace(filler, "")
            q = q.strip() or prompt

            await self._send_quick_ack(current_emotion)
            await self.send_message("speech", {"text": "", "emotion": "thinking"})
            result = await asyncio.to_thread(
                self.tools.execute_tool_call,
                "search_and_open",
                {"query": q, "max_results": 5},
            )
            speak = self._tool_result_for_speech("search_and_open", str(result))
            return speak or str(result), True

        # ── Intent: system control (音量/亮度/wifi/蓝牙) ──
        # Forward: "调高音量"
        sys_action = None
        sys_target = None
        m = re.search(
            r"(调[高大]|调[低小]|打开|关闭|关掉|开启|静音|取消静音)"
            r".{0,4}"
            r"(音量|亮度|声音|wifi|蓝牙|网络|WiFi|WIFI)",
            prompt
        )
        if m:
            sys_action = m.group(1)
            sys_target = m.group(2)
        else:
            # Reverse: "音量调高" / "亮度调高"
            m = re.search(
                r"(音量|亮度|声音|wifi|蓝牙|网络|WiFi|WIFI)"
                r".{0,4}"
                r"(调[高大]|调[低小]|大[一点些]|小[一点些]|高[一点些]|低[一点些]|打开|关闭|关掉|开启|静音|取消静音)",
                prompt
            )
            if m:
                sys_target = m.group(1)
                sys_action = m.group(2)

        if sys_action and sys_target:
            action_word = sys_action
            target_word = sys_target

            # Map target
            target_map = {
                "音量": "volume", "声音": "volume",
                "亮度": "brightness",
                "wifi": "wifi", "WiFi": "wifi", "WIFI": "wifi", "网络": "wifi",
                "蓝牙": "bluetooth",
            }
            target = target_map.get(target_word, target_word)

            # Map action
            if any(k in action_word for k in ["高", "大", "开", "启"]):
                action = "up" if target in ("volume", "brightness") else "on"
            elif any(k in action_word for k in ["低", "小"]):
                action = "down"
            elif "关" in action_word:
                action = "off" if target in ("wifi", "bluetooth") else "down"
            elif "静音" in action_word and "取消" not in action_word:
                action = "mute"
            elif "取消静音" in action_word:
                action = "unmute"
            else:
                action = "up"

            result = await asyncio.to_thread(
                self.tools.execute_tool_call,
                "system_control",
                {"target": target, "action": action},
            )
            return str(result), True

        # ── Intent: open app ──
        app_match = re.search(r"(?:打开|启动|开一下)\s*(.+?)(?:应用|app|APP)?[。，]?$", prompt)
        if app_match:
            app_name = app_match.group(1).strip()
            # Don't match if it looks like a website/search request
            if app_name and not any(k in app_name for k in ["网站", "网页", "视频", "搜", "查", "找"]):
                result = await asyncio.to_thread(
                    self.tools.execute_tool_call,
                    "open_app",
                    {"app_name": app_name},
                )
                return self._persona_wrap(str(result), "app"), True

        # ── Intent: get time ──
        if re.search(r"几点|什么时间|现在时间|当前时间", prompt):
            result = await asyncio.to_thread(
                self.tools.execute_tool_call,
                "get_time",
                {},
            )
            return str(result), True

        # No intent matched — let model handle it
        return None

    def _tool_result_for_speech(self, tool_name: str, tool_result: str) -> str:
        name = str(tool_name or "").strip()
        res = str(tool_result or "").strip()
        if not res:
            return ""
        if name in ("web_search", "smart_search"):
            return "我搜到了，想让我打开哪一个？"
        # Keep it short for TTS.
        if len(res) > 120:
            return res[:120]
        return res

    async def _run_tool_loop(
        self,
        user_input: str,
        memories: list,
        history: list,
        current_emotion: str,
        max_steps: int = 3,
    ) -> tuple[str, bool]:
        """Run a small tool loop and return (final_speech, executed_tools)."""
        prompt = str(user_input or "").strip()
        if not prompt:
            return "", False

        def normalize_task(text: str) -> str:
            t = str(text or "")
            t = t.replace("血关", "油管")
            t = t.replace("游馆", "油管")
            t = t.replace("游管", "油管")
            t = t.replace("油罐", "油管")
            t = t.replace("油館", "油管")
            return t

        prompt = normalize_task(prompt)

        executed_any = False
        observation = ""

        needs_action = any(tok in prompt for tok in ["搜索", "搜", "查", "找", "打开", "然后打开", "带我去"]) and (
            "然后" in prompt or "打开" in prompt
        )

        # ── Lightweight intent router ──
        # 1.2B model can't reliably pick the right tool for complex requests.
        # Detect common intents via keywords and route directly to the right
        # tool, skipping model inference. This is how production voice
        # assistants work (Siri, Alexa, etc.) — router + executor.
        import re as _re

        routed = await self._try_intent_route(prompt, current_emotion)
        if routed is not None:
            return routed

        for step in range(max_steps):
            full_response = ""
            tool_calls = []

            # Try twice: normal auto, then forced tool-call if request is clearly action.
            for attempt in range(2):
                full_response = ""
                auto_prompt = prompt
                if attempt == 1:
                    if needs_action:
                        auto_prompt = (
                            "你必须调用工具来完成用户请求。只输出 1 个工具调用，不要输出解释。\n"
                            f"用户请求: {prompt}"
                        )

                response_stream = await asyncio.to_thread(  # type: ignore[arg-type]
                    self._think_action,
                    auto_prompt,
                    memories,
                    history,
                    current_emotion,
                    "auto",
                )
                for chunk in response_stream:
                    full_response += getattr(chunk, "text", str(chunk))

                # Debug: log raw model output
                print(f"🤖 [DEBUG] Raw model output (attempt {attempt+1}): {full_response[:300]}", flush=True)

                # Strip <think>...</think> reasoning from Thinking model
                import re as _re2
                full_response = _re2.sub(r"<think>.*?</think>", "", full_response, flags=_re2.DOTALL)
                full_response = _re2.sub(r"<think>.*$", "", full_response, flags=_re2.DOTALL)
                full_response = full_response.strip()

                print(f"🤖 [DEBUG] After think-strip: {full_response[:200]}", flush=True)

                tool_calls = self.tools.parse_tool_calls(full_response)
                if tool_calls:
                    break

            if not tool_calls:
                # If this is clearly an action request, ask a concrete clarification.
                if needs_action:
                    return "你想在哪个平台找这个视频？YouTube 还是 B 站？", False
                # Otherwise treat as final assistant reply.
                return full_response, executed_any

            # Guard: if model uses open_url but user clearly wanted a search,
            # override to search_and_open to avoid fabricated URLs.
            if needs_action and step == 0:
                first_call = tool_calls[0]
                call_name = str(first_call.get("name") or "")
                if call_name == "open_url":
                    call_args = first_call.get("arguments") or first_call.get("parameters") or {}
                    url = str(call_args.get("url") or "")
                    # If the URL looks like a fabricated YouTube/video link, replace with real search
                    if any(d in url.lower() for d in ["youtube.com/watch", "youtu.be/", "bilibili.com/video"]):
                        prefer = []
                        low = prompt.lower()
                        if "油管" in low or "youtube" in low:
                            prefer = ["youtube.com", "youtu.be"]
                        elif "b站" in low or "bilibili" in low:
                            prefer = ["bilibili.com"]
                        tool_calls = [{
                            "name": "search_and_open",
                            "arguments": {
                                "query": prompt,
                                "prefer_domains": prefer,
                                "max_results": 5,
                            },
                        }]

            executed_any = True
            if step == 0:
                await self._send_quick_ack(current_emotion)
                # Send thinking emotion during multi-step execution
                await self.send_message("speech", {"text": "", "emotion": "thinking"})

            # Execute tools sequentially.
            obs_parts = []
            speak_parts = []
            for call in tool_calls:
                name = str(call.get("name") or "").strip()
                if not name:
                    continue
                arguments = call.get("arguments") or call.get("parameters")
                result = await asyncio.to_thread(self.tools.execute_tool_call, name, arguments)
                obs_parts.append(f"{name}: {result}")

                # Clarification loop for unknown apps.
                try:
                    if name == "open_app" and "没找到应用" in str(result) and "哪个应用" in str(result):
                        self.session.pending_action = {"type": "open_app"}
                        return str(result), True
                except Exception:
                    pass

                speak = self._tool_result_for_speech(name, str(result))
                if speak:
                    speak_parts.append(speak)

            observation = "\n".join(obs_parts).strip()

            # If a tool produced a speakable result, return immediately.
            # No need to ask the model "are you done?" — it just wastes time.
            if speak_parts:
                return "\n".join(speak_parts[:2]), True

            # Only ask model for next step if no speakable result yet
            # (e.g. a search returned raw data that needs interpretation).
            prompt = (
                "上一步工具返回:\n"
                f"{observation}\n\n"
                "如果需要继续操作就输出下一步工具调用；如果完成了就用中文一句话确认已完成（不要列链接）。"
            )

            # If we reached the last step, return a concise summary.
            if step == max_steps - 1:
                if speak_parts:
                    return "\n".join(speak_parts[:2]), True
                return "我处理好了。", True

        return "我处理好了。", executed_any

    async def mouth_speak(self, text, emotion="neutral"):
        """Speak and allow Frontend to sync lips and expression"""
        text = self._sanitize_for_speech(text)
        if not text:
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
        
        if audio_path:
            try:
                print(f"🔊 Playing audio: {audio_path}", flush=True)
            except Exception:
                pass
            # 4. Now we are ready to play. Signal Frontend!
            await self.send_state("SPEAKING")
            # Blocking Playback
            await asyncio.to_thread(self.mouth.play_audio_file, audio_path)
            # Done
            await self.send_state("IDLE")
        else:
            try:
                print("⚠️ TTS generation failed (no audio_path)", flush=True)
            except Exception:
                pass
            await self.send_state("IDLE")

    def _sanitize_for_speech(self, text: str) -> str:
        """Remove system artifacts and keep speech user-facing."""
        if text is None:
            return ""
        import re
        s = str(text)
        # Remove system blocks that should never be spoken.
        s = re.sub(r"<system-reminder>.*?</system-reminder>", "", s, flags=re.IGNORECASE | re.DOTALL)
        # Remove common model tokens.
        s = re.sub(r"<\|[^>]+\|>", "", s)
        # Collapse whitespace.
        s = " ".join(s.split())
        return s.strip()

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
            return self.tools.execute_tool_call("joke")
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
            pending = {
                "type": "chat_followup",
                "topic": topic,
                "asked": reply_s,
                "turns": 0,
            }
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
        cleaned = " ".join(text.split())

        # Strip <think>...</think> reasoning blocks from Thinking model
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
        # Also strip incomplete <think> blocks (model cut off mid-thought)
        cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)

        # Strip user-echo patterns: model sometimes repeats user input back
        # e.g. "用户：帮我找... 助手：请问你在哪里查看"
        cleaned = re.sub(r"用户[：:]\s*.*?助手[：:]\s*", "", cleaned)
        # Also strip standalone "用户：..." prefix
        cleaned = re.sub(r"^用户[：:]\s*.*$", "", cleaned, flags=re.MULTILINE)

        # Strip system tool/runtime artifacts if they ever leak into speech.
        cleaned = re.sub(
            r"<system-reminder>.*?</system-reminder>",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
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
            return self.tools.web_search(q, max_results=3)

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
            return self.tools.system_control("brightness", action)

        # 独立的静音命令
        if "静音" in text or "mute" in lower_text:
            action = "unmute" if "取消" in text or "un" in lower_text else "mute"
            print("🧭 Direct: system_control -> mute")
            return self.tools.system_control("volume", action)

        if "音量" in text or "声音" in text:
            action = "up"
            if any(token in text for token in ["小", "低", "降低", "调低"]):
                action = "down"
            print("🧭 Direct: system_control -> volume")
            return self.tools.system_control("volume", action)

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
            return self.tools.system_control("bluetooth", action)

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
            return self.tools.system_control("wifi", action)


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
                    return self.tools.system_control("app", "close", "Safari")
                # 其他应用
                if target:
                    print(f"🧭 Direct: close_app -> {target}")
                    return self.tools.system_control("app", "close", target)

        if "几点" in text or "时间" in text:
            print("🧭 Direct: get_time")
            return self._persona_wrap(self.tools.get_time(), "time")

        if "截图" in text or "截屏" in text:
            print("🧭 Direct: take_screenshot")
            return self._persona_wrap(self.tools.take_screenshot(), "screenshot")

        if "电量" in text or "电池" in text:
            print("🧭 Direct: battery_status")
            result = self.tools.run_terminal_cmd("pmset -g batt | grep -Eo '[0-9]+%'")
            battery = self._strip_cmd_output(result)
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
        result = self.tools.run_terminal_cmd("curl -s --max-time 4 https://ipinfo.io/city")
        city = self._strip_cmd_output(result).strip()
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

    def _fetch_weather_open_meteo(self, city: str) -> str:
        """Fallback weather provider using Open-Meteo (no API key)."""
        import json
        import urllib.parse
        import urllib.request

        name = str(city or "").strip()
        if not name:
            return ""

        # 1) Geocode
        geocode_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": name, "count": 1, "language": "zh", "format": "json"})
        )
        req = urllib.request.Request(geocode_url, headers={"User-Agent": "Kage/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        results = data.get("results") or []
        if not results:
            return ""
        r0 = results[0]
        lat = r0.get("latitude")
        lon = r0.get("longitude")
        disp = r0.get("name") or name
        if lat is None or lon is None:
            return ""

        # 2) Current weather
        forecast_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                    "timezone": "auto",
                }
            )
        )
        req2 = urllib.request.Request(forecast_url, headers={"User-Agent": "Kage/1.0"})
        with urllib.request.urlopen(req2, timeout=4) as resp:
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
        return f"{disp}: {desc} {t}°C"

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
        result = self.tools.run_terminal_cmd(
            f"curl -fsS --max-time 5 'wttr.in/{quote(city)}?format=3'"
        )
        weather = self._strip_cmd_output(result)
        # Handle timeouts / curl failures / empty output gracefully.
        if (
            not weather
            or weather.startswith("命令执行失败")
            or weather.startswith("命令执行超时")
            or weather.startswith("执行出错")
            or weather.startswith("命令执行成功")
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
            self.tools.open_app(default_app)
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
                    if hasattr(kage_server, "_text_input_queue"):
                        await kage_server._text_input_queue.put(msg["text"].strip())
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

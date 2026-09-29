"""
Model management and download API routes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import threading
import time
from uuid import uuid4
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


@router.get("/api/models/download")
async def list_model_downloads():
    import core.server as srv
    return srv._list_jobs()


@router.get("/api/models/download/{job_id}")
async def get_model_download(job_id: str):
    import core.server as srv
    job = srv._get_job(job_id)
    if not job:
        return {"error": "job not found"}
    return job


@router.post("/api/models/download")
async def start_model_download(payload: dict):
    import core.server as srv
    repo_id = str(payload.get("repo_id") or "").strip()
    revision = payload.get("revision")
    filename = str(payload.get("filename") or "").strip() or None
    variant = str(payload.get("variant") or "").strip() or None
    if not repo_id:
        return {"error": "repo_id required"}

    if not filename and variant:
        filename = srv._guess_qwen3_gguf_filename(repo_id, variant)
    if not filename:
        return {"error": "filename required (or provide variant for known repos)"}
    if not str(filename).lower().endswith(".gguf"):
        return {"error": "only .gguf downloads are supported by this endpoint"}

    m = re.match(r"^qwen3-(\d+(?:\.\d+)?)b-(q\d+_[a-z0-9_]+)\.gguf$", str(filename).strip(), flags=re.IGNORECASE)
    if m and repo_id.startswith("Qwen/") and repo_id.endswith("-GGUF"):
        size = m.group(1)
        variant_guess = m.group(2).upper()
        filename = f"Qwen3-{size}B-{variant_guess}.gguf"

    target_dir = str(payload.get("target_dir") or "").strip() or srv._get_models_dir()
    os.makedirs(target_dir, exist_ok=True)

    existing = srv._find_active_download_job(repo_id, revision=revision if isinstance(revision, str) else None, filename=filename)
    if existing:
        return {"job_id": existing, "status": "already_running"}

    job_id = uuid4().hex
    now = time.time()
    srv._download_jobs.create(
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
            "progress": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed_bps": 0.0,
            "error": None,
            "path": None,
        },
    )

    def _run():
        try:
            from huggingface_hub import hf_hub_download
            from tqdm.auto import tqdm

            class _JobTqdm(tqdm):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    srv._set_job(job_id, {"status": "running", "stage": "downloading", "updated_at": time.time()})

                def set_description_str(self, desc=None, refresh=True):
                    if desc:
                        srv._set_job(job_id, {"current_file": str(desc), "updated_at": time.time()})
                    return super().set_description_str(desc=desc, refresh=refresh)

                def update(self, n=1):
                    try:
                        cur = int(getattr(self, "n", 0) or 0)
                        srv._set_job(
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

            model_id = srv._make_model_id(repo_id, filename=filename, revision=revision if isinstance(revision, str) else None)
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
                srv._register_managed_model(entry)
            except Exception:
                pass

            srv._set_job(
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
            srv._set_job(job_id, {"status": "failed", "stage": "failed", "error": str(e), "updated_at": time.time()})

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@router.get("/api/models")
async def list_models():
    """List managed models (preferred) and legacy HF cache models."""
    import core.server as srv

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
        except Exception:
            logger.warning("Error listing models: %s", exc_info=True)

        return models

    managed = await asyncio.to_thread(srv._list_managed_models)
    hf_cache = await asyncio.to_thread(_scan_hf_cache_models)
    return {"managed": managed, "hf_cache": hf_cache}


@router.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    """Delete a model from cache."""
    import core.server as srv
    mid = str(model_id or "").strip()
    if not mid:
        return {"error": "Invalid model ID"}

    if not mid.startswith("models--"):
        return await asyncio.to_thread(srv._delete_managed_model, mid)

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


@router.get("/api/models/llama/status")
async def llama_status():
    import core.server as srv
    return srv._local_runtime.status()


@router.post("/api/models/llama/start")
async def llama_start(payload: dict):
    import core.server as srv
    req = payload if isinstance(payload, dict) else {}
    cfg = srv._load_effective_config()
    runtime_cfg = (
        cfg.get("model", {}).get("local_runtime", {})
        if isinstance(cfg.get("model", {}).get("local_runtime", {}), dict)
        else {}
    )
    merged = srv._deep_merge(runtime_cfg, req)
    result = srv._local_runtime.start(merged)
    return result.payload


@router.post("/api/models/llama/stop")
async def llama_stop():
    import core.server as srv
    return srv._local_runtime.stop()


@router.post("/api/models/activate")
async def activate_model(payload: dict):
    """Activate a model provider by writing a user config patch."""
    import core.server as srv
    provider = str(payload.get("provider") or "").strip() or "llama.cpp"
    if provider not in ("llama.cpp", "openai"):
        return {"error": "unsupported provider"}

    base_url = str(payload.get("base_url") or "").strip()
    model_name = str(payload.get("model_name") or "").strip() or "local-model"
    api_key = str(payload.get("api_key") or "").strip() or "local"

    if not base_url:
        st = srv._local_runtime.status()
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
    saved = srv._save_user_config_patch(patch)
    return {"status": "ok", "saved": saved}

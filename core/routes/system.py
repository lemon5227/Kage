"""
System and configuration API routes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/api/health")
async def health():
    import core.server as srv
    mode = os.environ.get("KAGE_MODE", "runtime").strip().lower()
    return {
        "ok": True,
        "mode": mode,
        "runtime_started": srv.kage_server is not None,
    }


@router.get("/api/config")
async def get_config():
    import core.server as srv
    return srv._load_effective_config()


@router.post("/api/config")
async def set_config(payload: dict):
    import core.server as srv
    if not isinstance(payload, dict):
        return {"error": "invalid payload"}
    saved = srv._save_user_config_patch(payload)
    return {"status": "ok", "saved": saved}


@router.get("/api/runtime/status")
async def runtime_status():
    import core.server as srv
    with srv._runtime_lock:
        return dict(srv._runtime_state)


@router.post("/api/runtime/start")
async def runtime_start():
    import core.server as srv
    with srv._runtime_lock:
        if srv.kage_server is not None:
            srv._runtime_state.update({
                "status": "ready",
                "stage": "ready",
                "error": None,
                "updated_at": time.time(),
            })
            return dict(srv._runtime_state)
        if srv._runtime_state.get("status") == "booting":
            return dict(srv._runtime_state)
        srv._runtime_state.update({
            "status": "booting",
            "stage": "starting",
            "started_at": time.time(),
            "error": None,
            "updated_at": time.time(),
        })

    def _boot():
        try:
            logger.info("Runtime boot requested")
            with srv._runtime_lock:
                srv._runtime_state.update({"stage": "loading_config", "updated_at": time.time()})
            cfg = srv._load_effective_config()
            with srv._runtime_lock:
                srv._runtime_state.update({"stage": "initializing_runtime", "updated_at": time.time()})

            srv.kage_server = srv.KageServer(config=cfg)
            logger.info("Runtime initialized")

            if srv._main_loop is not None:
                with srv._runtime_lock:
                    srv._runtime_state.update({"stage": "starting_main_loop", "updated_at": time.time()})

                def _start_loop_and_mark_ready():
                    try:
                        if srv.kage_server is None:
                            raise RuntimeError("runtime not initialized")
                        srv.kage_server.ensure_main_loop_started()
                        with srv._runtime_lock:
                            srv._runtime_state.update({
                                "status": "ready",
                                "stage": "ready",
                                "error": None,
                                "updated_at": time.time(),
                            })
                        logger.info("Runtime ready")
                    except Exception as e:
                        with srv._runtime_lock:
                            srv._runtime_state.update({
                                "status": "error",
                                "stage": "error",
                                "error": str(e),
                                "updated_at": time.time(),
                            })
                        logger.error("Runtime loop start failed: %s", e, exc_info=True)

                srv._main_loop.call_soon_threadsafe(_start_loop_and_mark_ready)
            else:
                with srv._runtime_lock:
                    srv._runtime_state.update({
                        "status": "ready",
                        "stage": "ready",
                        "error": None,
                        "updated_at": time.time(),
                    })
                logger.info("Runtime ready")
        except Exception as e:
            logger.error("Runtime boot failed: %s", e, exc_info=True)
            with srv._runtime_lock:
                srv._runtime_state.update({
                    "status": "error",
                    "stage": "error",
                    "error": str(e),
                    "updated_at": time.time(),
                })

    threading.Thread(target=_boot, daemon=True).start()
    return dict(srv._runtime_state)


@router.get("/api/settings/hybrid")
async def get_hybrid_settings():
    """Return current hybrid + cloud_api configuration for the settings UI."""
    import core.server as srv
    cfg = srv._load_effective_config()
    model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    hybrid_cfg = model_cfg.get("hybrid", {}) if isinstance(model_cfg, dict) else {}
    cloud_cfg = model_cfg.get("cloud_api", {}) if isinstance(model_cfg, dict) else {}
    api_key = str(cloud_cfg.get("api_key") or "")
    return {
        "enabled": bool(hybrid_cfg.get("enabled", False)),
        "escalate_keywords": list(hybrid_cfg.get("escalate_keywords") or []),
        "cloud_provider_type": str(cloud_cfg.get("provider_type") or "openai"),
        "cloud_model_name": str(cloud_cfg.get("model_name") or ""),
        "cloud_base_url": str(cloud_cfg.get("base_url") or ""),
        "cloud_key_configured": bool(api_key.strip()),
    }


@router.get("/api/settings/providers/detect")
async def detect_provider_credentials_endpoint():
    """Report which cloud-LLM credentials Kage can pick up from environment."""
    from core.credential_helpers import detect_provider_credentials
    return {"providers": detect_provider_credentials()}


@router.post("/api/settings/hybrid")
async def update_hybrid_settings(payload: dict):
    """Update hybrid mode + cloud_api settings."""
    import core.server as srv
    if not isinstance(payload, dict):
        return {"error": "InvalidInput", "message": "expected object body"}

    enabled = bool(payload.get("enabled", False))

    raw_keywords = payload.get("escalate_keywords") or []
    if isinstance(raw_keywords, str):
        raw_keywords = [s.strip() for s in raw_keywords.split(",")]
    keywords = [str(k).strip() for k in raw_keywords if str(k).strip()]

    cloud_patch: dict = {}

    provider_type = str(payload.get("cloud_provider_type") or "").strip().lower()
    if provider_type in ("openai", "anthropic"):
        cloud_patch["provider_type"] = provider_type

    api_key = str(payload.get("cloud_api_key") or "").strip()
    if api_key:
        cloud_patch["api_key"] = api_key
    else:
        env_provider = str(payload.get("use_env_key") or "").strip().lower()
        if env_provider:
            from core.credential_helpers import read_provider_credential
            env_key = read_provider_credential(env_provider)
            if env_key:
                cloud_patch["api_key"] = env_key
                if "provider_type" not in cloud_patch and env_provider in ("openai", "anthropic"):
                    cloud_patch["provider_type"] = env_provider

    model_name = str(payload.get("cloud_model_name") or "").strip()
    if model_name:
        cloud_patch["model_name"] = model_name
    base_url = str(payload.get("cloud_base_url") or "").strip()
    if base_url:
        cloud_patch["base_url"] = base_url

    patch: dict = {
        "model": {
            "hybrid": {
                "enabled": enabled,
                "escalate_keywords": keywords,
            },
        }
    }
    if cloud_patch:
        patch["model"]["cloud_api"] = cloud_patch

    saved = srv._save_user_config_patch(patch)

    server = srv._get_kage_server()
    reload_status = "skipped"
    if server is not None:
        try:
            server.reload_model_broker()
            reload_status = "applied"
        except Exception as exc:
            logger.warning("model broker reload failed: %s", exc)
            reload_status = f"failed: {exc}"

    return {"status": "ok", "saved": saved, "reload": reload_status}


@router.post("/api/settings/test_provider")
async def test_provider_endpoint(payload: dict):
    """Probe a cloud provider with a tiny ping to verify credentials."""
    import core.server as srv
    if not isinstance(payload, dict):
        return {"ok": False, "error": "InvalidInput: expected object body"}

    from core.provider_test import probe_provider as _probe

    provider_type = str(payload.get("provider_type") or "").strip().lower() or "openai"
    model_name = str(payload.get("model_name") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()

    api_key = ""
    if payload.get("use_stored"):
        cfg = srv._load_effective_config()
        cloud_cfg = (cfg.get("model") or {}).get("cloud_api") or {}
        api_key = str(cloud_cfg.get("api_key") or "").strip()
        if not provider_type or provider_type == "openai":
            provider_type = str(cloud_cfg.get("provider_type") or "openai").strip().lower() or "openai"
        if not model_name:
            model_name = str(cloud_cfg.get("model_name") or "").strip()
        if not base_url:
            base_url = str(cloud_cfg.get("base_url") or "").strip()
    else:
        api_key = str(payload.get("api_key") or "").strip()
        if not api_key:
            env_provider = str(payload.get("use_env_key") or "").strip().lower()
            if env_provider:
                from core.credential_helpers import read_provider_credential
                api_key = read_provider_credential(env_provider)
                if api_key and provider_type == "openai" and env_provider in ("openai", "anthropic"):
                    provider_type = env_provider

    result = _probe(
        provider_type=provider_type,
        api_key=api_key,
        model_name=model_name,
        base_url=base_url,
    )
    return result.to_dict()

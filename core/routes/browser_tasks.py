"""HTTP entry point for controlled browser experiments."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.computer_use.task_service import BrowserTaskService

router = APIRouter(prefix='/api/browser', tags=['browser-experiments'])
logger = logging.getLogger(__name__)
_service: BrowserTaskService | None = None
_service_lock = Lock()
_notification_tasks: set[asyncio.Task] = set()
NOTIFICATION_TIMEOUT_SECONDS = 5.0
NOTIFICATION_CLEANUP_SECONDS = 0.25


def _track_notification(task: asyncio.Task) -> None:
    _notification_tasks.add(task)

    def settled(done: asyncio.Task) -> None:
        _notification_tasks.discard(done)
        if not done.cancelled():
            try:
                done.exception()
            except Exception as exc:
                logger.warning('Browser job notification failed: %s', type(exc).__name__)

    task.add_done_callback(settled)


async def _deliver_notification(runtime, event: str, job: dict) -> None:
    delivery = asyncio.create_task(runtime._notify_job_event(event, job))
    _track_notification(delivery)
    done, pending = await asyncio.wait({delivery}, timeout=NOTIFICATION_TIMEOUT_SECONDS)
    if pending:
        delivery.cancel()
        logger.warning('Browser job notification timed out')
    else:
        try:
            delivery.result()
        except Exception as exc:
            logger.warning('Browser job notification failed: %s', type(exc).__name__)


async def _notify_runtime(event: str, job: dict) -> None:
    import core.server as server
    runtime = server.kage_server
    if runtime is None:
        return
    # Event delivery may include websocket I/O and speech. It cannot hold the
    # serial worker's started event or a run-bound stop/shutdown response.
    _track_notification(asyncio.create_task(_deliver_notification(runtime, event, job)))


def _get_service() -> BrowserTaskService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                import core.server as server
                root = os.environ.get('KAGE_BROWSER_RUNS_DIR') or '~/.kage/browser-runs'
                _service = BrowserTaskService(Path(root), server._load_effective_config, _notify_runtime)
    return _service


async def close_service() -> None:
    global _service
    with _service_lock:
        service, _service = _service, None
    try:
        if service is not None:
            await service.close()
    finally:
        tasks = tuple(_notification_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=NOTIFICATION_CLEANUP_SECONDS)
            if pending:
                logger.warning('Browser job notification cleanup timed out')


@router.get('/catalog')
def catalog():
    return _get_service().catalog()


@router.post('/tasks', status_code=202)
async def create_task(payload: dict):
    try:
        return await _get_service().submit(payload)
    except ValueError as exc:
        message = str(exc)
        status = 409 if any(key in message for key in ('model.', 'cloud ', 'selected executor', 'credential')) else 422
        raise HTTPException(status_code=status, detail=message) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get('/tasks')
def list_tasks():
    return _get_service().list()


@router.get('/tasks/{run_id}')
def get_task(run_id: str):
    job = _get_service().get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail='browser run not found')
    return job


@router.post('/tasks/{run_id}/stop')
async def stop_task(run_id: str):
    job = await _get_service().stop(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail='browser run not found')
    return job


@router.get('/tasks/{run_id}/artifacts/{name:path}')
def get_artifact(run_id: str, name: str):
    path = _get_service().artifact(run_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail='artifact not found')
    return FileResponse(path)

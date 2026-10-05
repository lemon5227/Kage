"""Teaching sessions reuse the browser jobs' bounded runtime notification bridge."""
import os
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.computer_use.demonstration_service import BrowserDemonstrationService
from core.routes.browser_tasks import _notify_runtime

router = APIRouter(prefix='/api/browser/demonstrations', tags=['browser-demonstrations'])
_service = None
_service_lock = Lock()


def _get_service():
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = BrowserDemonstrationService(Path(os.environ.get('KAGE_BROWSER_DEMONSTRATIONS_DIR') or
                    '~/.kage/browser-demonstrations'), lambda: {}, _notify_runtime)
    return _service


async def close_service():
    global _service
    with _service_lock:
        service, _service = _service, None
    if service:
        await service.close()


async def _call(method, *args):
    try:
        job = await method(*args)
        if job is None:
            raise LookupError('browser demonstration not found')
        return job
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/catalog')
def catalog():
    return _get_service().catalog()


@router.post('', status_code=202)
async def submit(payload: dict):
    return await _call(_get_service().submit, payload)


@router.get('')
def list_sessions():
    return _get_service().list()


@router.get('/{run_id}')
def get_session(run_id: str):
    job = _get_service().get(run_id)
    if job is None:
        raise HTTPException(404, 'browser demonstration not found')
    return job


@router.post('/{run_id}/finish')
async def finish(run_id: str):
    return await _call(_get_service().finish, run_id)


@router.post('/{run_id}/stop')
async def stop(run_id: str):
    return await _call(_get_service().stop, run_id)


@router.post('/{run_id}/replay', status_code=202)
async def replay(run_id: str, payload: dict):
    return await _call(_get_service().replay, run_id, payload)


@router.get('/{run_id}/artifacts/{name:path}')
def artifact(run_id: str, name: str):
    path = _get_service().artifact(run_id, name)
    if path is None:
        raise HTTPException(404, 'artifact not found')
    return FileResponse(path)

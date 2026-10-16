"""Usage-time trajectory store API (A2): inspect, delete, switch off, export redacted.

Raw records never leave this Mac through these routes; only /export writes a redacted file
(train split, task turns with success evidence) for later training.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["trajectories"])
EXPORT_PATH = Path('~/.kage/trajectories-export/redacted.jsonl')


def _recorder():
    import core.server as srv
    kage = srv._get_kage_server()
    return getattr(kage, "trajectories", None) if kage else None


@router.get("/api/trajectories")
async def list_trajectories():
    rec = _recorder()
    if rec is None:
        return {"error": "trajectory store not available"}
    rows = rec.list()
    return {"enabled": rec.enabled, "root": str(rec.root), "total": len(rows), "items": rows}


@router.get("/api/trajectories/{turn_id}")
async def get_trajectory(turn_id: str):
    rec = _recorder()
    record = rec.get(turn_id) if rec else None
    return record or {"error": "not found"}


@router.delete("/api/trajectories/{turn_id}")
async def delete_trajectory(turn_id: str):
    rec = _recorder()
    return {"deleted": rec.delete(turn_id) if rec else 0}


@router.delete("/api/trajectories")
async def delete_all_trajectories():
    rec = _recorder()
    return {"deleted": rec.delete(None) if rec else 0}


@router.put("/api/trajectories/enabled")
async def set_enabled(enabled: bool):
    rec = _recorder()
    if rec is None:
        return {"error": "trajectory store not available"}
    rec.enabled = bool(enabled)
    return {"enabled": rec.enabled}


@router.post("/api/trajectories/export")
async def export_trajectories():
    from core.trajectories import export_redacted
    rec = _recorder()
    if rec is None:
        return {"error": "trajectory store not available"}
    out = Path(os.path.expanduser(str(EXPORT_PATH)))
    return {"path": str(out), **export_redacted(rec, out)}

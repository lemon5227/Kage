"""
Memory inspection and management API routes.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memory"])


@router.get("/api/memory/stats")
async def memory_stats():
    """Get memory system statistics."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "memory"):
        return {"error": "memory system not available"}
    return kage.memory.get_stats()


@router.get("/api/memory/entries")
async def memory_entries(limit: int = 50, offset: int = 0, category: str = ""):
    """List memory entries with optional filtering."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "memory"):
        return {"error": "memory system not available"}

    entries, total = kage.memory.get_entries(limit=limit, offset=offset, category=category)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": entries,
    }


@router.post("/api/memory/deduplicate")
async def memory_deduplicate(threshold: float = 0.85):
    """Remove duplicate memory entries."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "memory"):
        return {"error": "memory system not available"}

    removed = kage.memory.deduplicate_memories(similarity_threshold=threshold)
    return {"status": "success", "removed": removed}


@router.post("/api/memory/merge")
async def memory_merge(threshold: float = 0.75):
    """Merge similar memory entries."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "memory"):
        return {"error": "memory system not available"}

    merged = kage.memory.merge_similar_facts(similarity_threshold=threshold)
    return {"status": "success", "merged": merged}


@router.get("/api/memory/profile")
async def memory_profile():
    """Get the user profile summary."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "prompt_builder") or not kage.prompt_builder.profile:
        return {"error": "profile not available"}

    return {
        "profile": kage.prompt_builder.profile.to_dict(),
        "summary": kage.prompt_builder.profile.get_profile_summary(),
    }


@router.get("/api/memory/profile/history")
async def memory_profile_history():
    """Get profile version history."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "prompt_builder") or not kage.prompt_builder.profile:
        return {"error": "profile not available"}

    versions = kage.prompt_builder.profile.get_version_history()
    return {"versions": versions}


@router.post("/api/memory/profile/restore/{version}")
async def memory_profile_restore(version: int):
    """Restore a previous profile version."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "prompt_builder") or not kage.prompt_builder.profile:
        return {"error": "profile not available"}

    success = kage.prompt_builder.profile.restore_version(version)
    if success:
        return {"status": "success", "restored_version": version}
    return {"status": "error", "message": "version not found"}


@router.post("/api/memory/forget")
async def memory_forget(max_age_days: int = 90, min_importance: int = 2):
    """Automatically forget old, low-importance memories."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "memory"):
        return {"error": "memory system not available"}

    forgotten = kage.memory.forget_old_memories(
        max_age_days=max_age_days,
        min_importance=min_importance,
    )
    return {"status": "success", "forgotten": forgotten}


@router.delete("/api/memory/entries/{entry_id}")
async def memory_delete_entry(entry_id: str):
    """Delete a specific memory entry."""
    import core.server as srv
    kage = srv._get_kage_server()
    if not kage or not hasattr(kage, "memory"):
        return {"error": "memory system not available"}

    success = kage.memory.delete_entry(entry_id)
    if success:
        return {"status": "success", "deleted": entry_id}
    return {"status": "error", "message": "entry not found"}

"""Memory tools — recall search."""

import json

from core.tools._response import err


def memory_search(query: str, n_results: int = 5, memory_system=None) -> str:
    """Search memory system."""
    if memory_system is None:
        return err("NotAvailable", "Memory system not available")
    try:
        results = memory_system.recall(query, n_results=n_results)
        return json.dumps({"success": True, "results": results}, ensure_ascii=False)
    except Exception as e:
        return err("SearchFailed", str(e))

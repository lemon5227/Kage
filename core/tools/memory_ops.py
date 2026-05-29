"""Memory and agent tools."""

import json


def memory_search(query: str, n_results: int = 5, memory_system=None) -> str:
    """Search memory system."""
    if memory_system is None:
        return json.dumps({"error": "NotAvailable", "message": "Memory system not available"}, ensure_ascii=False)
    try:
        results = memory_system.recall(query, n_results=n_results)
        return json.dumps({"results": results}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "SearchFailed", "message": str(e)}, ensure_ascii=False)


def proactive_agent(skill_name: str, description: str, steps: str = "", skills_dir: str = "skills") -> str:
    """Create a skill file programmatically."""
    import os
    sd = os.path.expanduser(skills_dir)
    os.makedirs(sd, exist_ok=True)
    skill_file = os.path.join(sd, f"{skill_name}.md")
    content = f"# {skill_name}\n\n{description}\n\n## Steps\n\n{steps or 'TODO: Add steps'}\n"
    try:
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"success": True, "path": skill_file}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "CreateFailed", "message": str(e)}, ensure_ascii=False)

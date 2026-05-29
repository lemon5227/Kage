"""Agent tools — proactive agent creation."""

import json
import os


def proactive_agent(skill_name: str, description: str, steps: str = "", skills_dir: str = "skills") -> str:
    """Create a skill file programmatically."""
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

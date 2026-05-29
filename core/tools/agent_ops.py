"""Agent tools — proactive skill creation."""

import os

from core.tools._response import ok, err


def proactive_agent(skill_name: str, description: str, steps: str = "", skills_dir: str = "skills") -> str:
    """Create a skill file programmatically."""
    sd = os.path.expanduser(skills_dir)
    os.makedirs(sd, exist_ok=True)
    skill_file = os.path.join(sd, f"{skill_name}.md")
    content = f"# {skill_name}\n\n{description}\n\n## Steps\n\n{steps or 'TODO: Add steps'}\n"
    try:
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(content)
        return ok(path=skill_file)
    except Exception as e:
        return err("CreateFailed", str(e))

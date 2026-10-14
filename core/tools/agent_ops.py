"""Agent tools — proactive skill creation."""

import os

from core.tools._response import ok, err
from core.tools.skill_ops import SKILL_NAME_RE


def proactive_agent(skill_name: str, description: str, steps: str = "", skills_dir: str = "skills") -> str:
    """Create a skill file programmatically."""
    skill_name = str(skill_name or "").strip()
    if not SKILL_NAME_RE.fullmatch(skill_name):
        # The name becomes a file name; reject separators/".." so it cannot escape skills_dir.
        return err("InvalidArgument", "技能名需为 1-64 位字母/数字/. _ -，且不能包含路径分隔符")
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

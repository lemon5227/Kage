"""Skill management tools — find, install, list, read, save."""

import os
import re
import shutil
import subprocess
import logging

from core.tools._response import ok, err

logger = logging.getLogger(__name__)


def ensure_node_tools() -> tuple[bool, str]:
    """Check if Node.js/npx is available."""
    if shutil.which("node") is None or shutil.which("npx") is None:
        return False, "未检测到 Node.js/npx。技能生态能力需要 Node.js。macOS 可用: brew install node (或使用 nvm)。"
    return True, ""


def run_npx(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run npx with best-effort stable flags."""
    env = os.environ.copy()
    env.setdefault("DO_NOT_TRACK", "1")
    env.setdefault("DISABLE_TELEMETRY", "1")
    try:
        proc = subprocess.run(
            ["npx", *args],
            capture_output=True,
            text=True,
            timeout=max(1, min(120, int(timeout))),
            env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return 1, "", str(exc)


def parse_skills_find_output(text: str, max_results: int = 5) -> list[dict]:
    """Parse npx skills find output."""
    out: list[dict] = []
    seen: set[str] = set()
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines) and len(out) < max_results:
        line = lines[i].strip()
        m = re.match(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+)$", line)
        if m:
            repo, skill = m.group(1), m.group(2)
            key = f"{repo}@{skill}"
            url = ""
            if i + 1 < len(lines):
                m2 = re.search(r"https?://skills\.sh/\S+", lines[i + 1])
                if m2:
                    url = m2.group(0)
            if key not in seen:
                seen.add(key)
                out.append({"repo": repo, "skill": skill, "ref": key, "url": url})
            i += 2
            continue
        i += 1
    return out


def find_skills(query: str, max_results: int = 5, skills_dir: str = "skills") -> str:
    """Find skills locally and via npx."""
    have_node, msg = ensure_node_tools()
    if not have_node:
        return err("NodeNotFound", msg)
    rc, stdout, stderr = run_npx(["skills", "find", query], timeout=30)
    if rc != 0:
        return err("NPXFailed", stderr or "npx skills find failed")
    skills = parse_skills_find_output(stdout, max_results)
    return ok(skills=skills)


def skills_find_remote(query: str, max_results: int = 5) -> str:
    """Find skills from remote registry."""
    return find_skills(query, max_results)


def skills_install(repo: str, skill: str, global_install: bool = True, agent: str = "opencode") -> str:
    """Install a skill from a remote repo."""
    have_node, msg = ensure_node_tools()
    if not have_node:
        return err("NodeNotFound", msg)
    flags = ["--yes", "--"]
    if global_install:
        flags.append("-g")
    rc, stdout, stderr = run_npx(["skills", "install", f"{repo}@{skill}", *flags], timeout=60)
    if rc != 0:
        return err("InstallFailed", stderr or "npx skills install failed")
    return ok(message=stdout)


def skills_list(global_install: bool = True, agent: str = "opencode") -> str:
    """List installed skills."""
    have_node, msg = ensure_node_tools()
    if not have_node:
        return err("NodeNotFound", msg)
    flags = ["--yes", "--"]
    if global_install:
        flags.append("-g")
    rc, stdout, stderr = run_npx(["skills", "list", *flags], timeout=30)
    if rc != 0:
        return err("ListFailed", stderr or "npx skills list failed")
    return ok(skills=stdout)


def skills_read(skill_name: str, workspace_dir: str = "~/.kage") -> str:
    """Read skill content."""
    have_node, msg = ensure_node_tools()
    if not have_node:
        return err("NodeNotFound", msg)
    rc, stdout, stderr = run_npx(["skills", "read", skill_name], timeout=30)
    if rc != 0:
        return err("ReadFailed", stderr or f"Cannot read skill: {skill_name}")
    return ok(skill=skill_name, content=stdout)


def skills_save_local(skill_name: str, content: str, workspace_dir: str = "~/.kage") -> str:
    """Save a skill locally."""
    ws = os.path.expanduser(workspace_dir)
    skills_dir = os.path.join(ws, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    skill_file = os.path.join(skills_dir, f"{skill_name}.md")
    try:
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(content)
        return ok(path=skill_file)
    except Exception as e:
        return err("SaveFailed", str(e))

"""Skill management tools — find, install, list, read, save."""

import json
import os
import re
import shutil
import subprocess
import logging
from pathlib import Path

from core.skill_parser import default_skill_sources, scan_skill_sources
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
    """Find locally available skills by name or description."""
    terms = str(query or "").strip().casefold().split()
    if not terms:
        return err("InvalidArgument", "query 不能为空")
    sources = [*default_skill_sources(), skills_dir]
    matches = []
    for skill in scan_skill_sources(sources):
        haystack = f"{skill.name} {skill.title} {skill.description}".casefold()
        if all(term in haystack for term in terms):
            matches.append({
                "name": skill.name,
                "description": skill.description,
                "source": "local",
            })
    try:
        limit = max(1, min(5, int(max_results)))
    except (TypeError, ValueError):
        return err("InvalidArgument", f"max_results 必须为整数，收到 {max_results!r}")
    return ok(skills=matches[:limit])


def skills_find_remote(query: str, max_results: int = 5) -> str:
    """Find skills from the remote registry."""
    have_node, msg = ensure_node_tools()
    if not have_node:
        return err("NodeNotFound", msg)
    rc, stdout, stderr = run_npx(["skills", "find", query], timeout=30)
    if rc != 0:
        return err("NPXFailed", stderr or "npx skills find failed")
    skills = parse_skills_find_output(stdout, max_results)
    return ok(skills=skills)


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
    clean = str(skill_name or "").strip()
    if SKILL_NAME_RE.fullmatch(clean):
        for source in default_skill_sources(workspace_dir):
            directory = Path(source).expanduser()
            for candidate in (directory / f"{clean}.md", directory / clean / "SKILL.md"):
                if candidate.is_file():
                    try:
                        return ok(skill=clean, content=candidate.read_text(encoding="utf-8"))
                    except OSError as exc:
                        return err("ReadFailed", str(exc))
    have_node, msg = ensure_node_tools()
    if not have_node:
        return err("NodeNotFound", msg)
    rc, stdout, stderr = run_npx(["skills", "read", skill_name], timeout=30)
    if rc != 0:
        return err("ReadFailed", stderr or f"Cannot read skill: {skill_name}")
    return ok(skill=skill_name, content=stdout)


SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_SKILLS_DIR = "~/.kage/skills"


def _render_skill_markdown(name: str, description: str, body: str) -> str:
    """Frontmatter + body. Scalars are JSON-quoted, which is valid YAML, so this
    does not add a PyYAML dependency (it is not declared in requirements.txt)."""
    desc = json.dumps(str(description or "").strip(), ensure_ascii=False)
    text = str(body or "")
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n{text.rstrip()}\n"


def skills_save_local(name: str, description: str = "", body: str = "",
                      target_dir: str = DEFAULT_SKILLS_DIR, overwrite: bool = False) -> str:
    """Save a local skill markdown file.

    Signature matches the registered tool schema (name/description/body/target_dir/
    overwrite). It previously read (skill_name, content, workspace_dir) while the
    schema advertised the former names, so *every* model-issued call raised
    ``TypeError: unexpected keyword argument 'name'``.

    The skill name is validated instead of interpolated into a path: the old
    implementation accepted ``../../x`` and wrote outside the skills directory.
    """
    clean = str(name or "").strip().lower()
    if not clean or not SKILL_NAME_RE.match(clean):
        return err("InvalidArgument", "技能名需为 1-64 位字母/数字/. _ -，且不能包含路径分隔符")

    desc = str(description or "").strip()
    if not desc:
        return err("InvalidArgument", "description 不能为空")

    try:
        skills_dir = Path(str(target_dir or DEFAULT_SKILLS_DIR)).expanduser().resolve()
    except Exception as e:
        return err("InvalidArgument", f"target_dir 无效: {e}")

    skill_file = skills_dir / f"{clean}.md"
    if skill_file.exists() and not overwrite:
        return err("AlreadyExists", f"技能已存在: {skill_file}（覆盖请传 overwrite=true）")

    rendered = _render_skill_markdown(clean, desc, body)
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(rendered, encoding="utf-8")
        return ok(path=str(skill_file), name=clean,
                  bytes_written=len(rendered.encode("utf-8")))
    except Exception as e:
        return err("SaveFailed", str(e))

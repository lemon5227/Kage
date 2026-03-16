"""core.skill_parser

SKILL.md 解析与扫描。

兼容两种技能格式：
1) Agent Skills 规范 (skills.sh / npx skills)：YAML frontmatter，包含 name/description。
2) 旧版 Kage skills/*.md：使用 `# 标题` + `## 描述` 段落。

本模块只做“发现与读取”，不负责执行。
"""

import os
import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """解析后的 SKILL.md 信息"""
    name: str
    filename: str
    title: str
    description: str
    full_content: str


def _parse_frontmatter(md: str) -> dict:
    """Parse minimal YAML frontmatter.

    We intentionally avoid adding a YAML dependency.
    Supports simple `key: value` pairs for common Agent Skills fields.
    """
    text = md or ""
    lines = text.splitlines()
    if len(lines) < 3:
        return {}
    if lines[0].strip() != "---":
        return {}
    # Find closing ---
    end = None
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm_lines = lines[1:end]
    out: dict[str, str] = {}
    for line in fm_lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if not key:
            continue
        # Only keep common top-level fields to avoid pretending we parse full YAML.
        if key in ("name", "description"):
            out[key] = val
    return out


def parse_skill_file(filepath: str) -> Optional[SkillInfo]:
    """解析单个 SKILL.md 文件，提取标题和描述。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("无法读取技能文件 %s: %s", filepath, exc)
        return None

    # 1) Agent Skills frontmatter (skills.sh)
    fm = _parse_frontmatter(content)
    fm_name = str(fm.get("name") or "").strip()
    fm_desc = str(fm.get("description") or "").strip()
    if fm_name and fm_desc:
        # Title: try first markdown H1; fallback to name.
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = (title_match.group(1).strip() if title_match else fm_name)
        return SkillInfo(
            name=fm_name,
            filename=os.path.basename(filepath),
            title=title,
            description=fm_desc,
            full_content=content,
        )

    # 2) Legacy markdown format: `# 标题` + `## 描述`
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if not title_match:
        logger.warning("技能文件缺少标题/frontmatter: %s", filepath)
        return None
    title = title_match.group(1).strip()

    desc_match = re.search(
        r"^##\s*描述\s*\n(.*?)(?=^##|\Z)",
        content, re.MULTILINE | re.DOTALL,
    )
    description = desc_match.group(1).strip() if desc_match else ""
    if not description:
        # For legacy skills, allow empty description but keep indexable title.
        description = ""
    # Name fallback: slugify title
    safe = re.sub(r"[^a-zA-Z0-9\-]+", "-", title).strip("-")
    safe = safe.lower() or os.path.basename(filepath).split(".")[0]

    return SkillInfo(
        name=safe,
        filename=os.path.basename(filepath),
        title=title,
        description=description,
        full_content=content,
    )


def scan_skills_directory(skills_dir: str = "skills") -> list[SkillInfo]:
    """扫描一个目录下的技能。

    兼容：
    - skills/*.md (legacy)
    - skills/**/SKILL.md (Agent Skills)
    """
    if not os.path.isdir(skills_dir):
        return []
    results: list[SkillInfo] = []

    # 1) legacy flat .md files
    for filename in sorted(os.listdir(skills_dir)):
        if not filename.endswith(".md") or filename == "README.md":
            continue
        filepath = os.path.join(skills_dir, filename)
        if os.path.isdir(filepath):
            continue
        info = parse_skill_file(filepath)
        if info:
            results.append(info)

    # 2) Agent Skills: recursive SKILL.md
    for root, _dirs, files in os.walk(skills_dir):
        for f in files:
            if f != "SKILL.md":
                continue
            fp = os.path.join(root, f)
            info = parse_skill_file(fp)
            if info:
                results.append(info)

    return results


def default_skill_sources(workspace_dir: str = "~/.kage") -> list[str]:
    """Return a list of directories to scan for SKILL.md.

    Includes repo-local and common global install locations.
    """
    ws = os.path.expanduser(workspace_dir)
    return [
        os.path.join(os.getcwd(), "skills"),
        os.path.join(os.getcwd(), "outer_skills"),
        os.path.join(ws, "skills"),
        os.path.expanduser("~/.config/opencode/skills"),
        os.path.expanduser("~/.config/agents/skills"),
    ]


def scan_skill_sources(sources: list[str]) -> list[SkillInfo]:
    """Scan multiple skill source directories."""
    out: list[SkillInfo] = []
    seen: set[tuple[str, str]] = set()
    for src in sources:
        if not src:
            continue
        if not os.path.isdir(src):
            continue
        for info in scan_skills_directory(src):
            key = (info.name, info.filename)
            if key in seen:
                continue
            seen.add(key)
            out.append(info)
    return out

import os
import json
import subprocess

SKILL_INFO = {
    "name": "find-skills",
    "description": "Helps users discover and install agent skills when they ask questions like \"how do I do X\", \"find a skill for X\", \"is there a skill that can...\", or express interest in extending capabilities. This skill should be used when the user is looking for functionality that might exist as an installable skill.",
    "triggers": ["findskills", "find skills", "find-skills", "找技能", "技能推荐", "技能搜索"],
    "action": "find-skills",
    "parameters": {"type": "object", "properties": {}}
}

SKILL_PATH = "outer_skills/find-skills/SKILL.md"
SCRIPTS_DIR = "/Users/wenbo/Kage/outer_skills/find-skills/scripts"

def execute(params: str) -> str:
    payload = _parse_params(params)
    if payload.get("list_scripts"):
        return _list_scripts()
    script = payload.get("script")
    if script:
        return _run_script(script, payload.get("args"))
    return _read_skill()

def _read_skill() -> str:
    if not os.path.exists(SKILL_PATH):
        return "未找到技能文件，请确认 outer_skills 已同步"
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()
    content = _strip_frontmatter(content)
    if len(content) > 1200:
        content = content[:1200] + "..."
    return "技能指引:" + "\n" + content

def _list_scripts() -> str:
    if not os.path.isdir(SCRIPTS_DIR):
        return "该技能没有 scripts 目录"
    files = sorted(os.listdir(SCRIPTS_DIR))
    if not files:
        return "scripts 目录为空"
    return "可用脚本: " + ", ".join(files)

def _run_script(script_name: str, args) -> str:
    if not os.path.isdir(SCRIPTS_DIR):
        return "该技能没有 scripts 目录"
    safe_name = os.path.basename(script_name)
    script_path = os.path.join(SCRIPTS_DIR, safe_name)
    if not os.path.exists(script_path):
        return "脚本不存在: " + safe_name
    cmd = []
    if script_path.endswith(".py"):
        cmd = ["python3", script_path]
    elif script_path.endswith(".sh"):
        cmd = ["bash", script_path]
    else:
        return "仅支持 .py 或 .sh 脚本"
    if isinstance(args, list):
        cmd.extend([str(a) for a in args])
    elif isinstance(args, str) and args:
        cmd.append(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except Exception as exc:
        return "脚本执行失败: " + str(exc)
    output = (result.stdout or result.stderr).strip()
    return output or "脚本执行完成"

def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return content
    return parts[2].strip()

def _parse_params(params):
    if not params:
        return {}
    if isinstance(params, dict):
        return params
    try:
        return json.loads(params)
    except Exception:
        return {}

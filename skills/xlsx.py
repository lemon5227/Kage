import os
import json
import subprocess

SKILL_INFO = {
    "name": "xlsx",
    "description": "Comprehensive spreadsheet creation, editing, and analysis with support for formulas, formatting, data analysis, and visualization. When Claude needs to work with spreadsheets (.xlsx, .xlsm, .csv, .tsv, etc) for: (1) Creating new spreadsheets with formulas and formatting, (2) Reading or analyzing data, (3) Modify existing spreadsheets while preserving formulas, (4) Data analysis and visualization in spreadsheets, or (5) Recalculating formulas",
    "triggers": ["xlsx", "表格", "Excel", "电子表格", "写表格", "excel"],
    "action": "xlsx",
    "parameters": {"type": "object", "properties": {}}
}

SKILL_PATH = "outer_skills/xlsx/SKILL.md"
SCRIPTS_DIR = "/Users/wenbo/Kage/outer_skills/xlsx/scripts"

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

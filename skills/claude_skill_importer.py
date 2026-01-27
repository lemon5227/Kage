import os
import re


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SEARCH_DIRS = [
    os.path.join(BASE_DIR, "outer_skills"),
    os.path.join(BASE_DIR, "claude_skills"),
    os.path.join(BASE_DIR, ".skills"),
    os.path.expanduser("~/.skills"),
]


def main():
    skill_paths = find_skill_markdowns(DEFAULT_SEARCH_DIRS)
    if not skill_paths:
        print("No SKILL.md files found in outer_skills/.skills.")
        return

    created = 0
    for skill_md in skill_paths:
        data = parse_frontmatter(skill_md)
        if not data:
            print(f"Skipping {skill_md}: missing frontmatter")
            continue
        name = data.get("name")
        description = data.get("description")
        if not name or not description:
            print(f"Skipping {skill_md}: missing name/description")
            continue

        target_path = build_target_path(name)
        triggers = build_triggers(name)
        script_hint = ""
        if has_scripts_dir(skill_md):
            script_hint = " (该 skill 含 scripts/ 目录，可手动执行)"

        content = render_skill_file(name, description, triggers, skill_md, script_hint)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        created += 1
        print(f"Generated: {os.path.relpath(target_path, BASE_DIR)}")

    print(f"Done. Generated {created} skills.")


def find_skill_markdowns(search_dirs):
    results = []
    for base in search_dirs:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            if "SKILL.md" in files:
                results.append(os.path.join(root, "SKILL.md"))
    return results


def parse_frontmatter(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines or not lines[0].strip().startswith("---"):
        return None
    frontmatter = {}
    idx = 1
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("---"):
            break
        if ":" not in stripped:
            idx += 1
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if value:
            frontmatter[key] = value
            idx += 1
            continue
        idx += 1
        collected = []
        while idx < len(lines):
            next_line = lines[idx]
            if next_line.strip().startswith("---"):
                break
            if next_line.startswith(" ") or next_line.startswith("\t"):
                collected.append(next_line.strip())
                idx += 1
                continue
            if ":" in next_line:
                break
            idx += 1
        if collected:
            frontmatter[key] = " ".join(collected)
    return frontmatter


def build_target_path(name):
    filename = to_snake_case(name) or "skill"
    target_dir = os.path.join(BASE_DIR, "skills")
    os.makedirs(target_dir, exist_ok=True)
    candidate = os.path.join(target_dir, f"{filename}.py")
    if not os.path.exists(candidate):
        return candidate
    idx = 2
    while True:
        candidate = os.path.join(target_dir, f"{filename}_{idx}.py")
        if not os.path.exists(candidate):
            return candidate
        idx += 1


def to_snake_case(value):
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


def build_triggers(name):
    base = name.replace("-", " ").replace("_", " ").strip()
    tokens = [t for t in base.split(" ") if t]
    if not tokens:
        return [name]
    joined = "".join(tokens)
    spaced = " ".join(tokens)
    triggers = []
    if joined:
        triggers.append(joined)
    if spaced and spaced != joined:
        triggers.append(spaced)
    if name not in triggers:
        triggers.append(name)
    extra = {
        "social-content": ["社媒内容", "社交内容", "社媒文案", "写社媒", "社交媒体内容"],
        "find-skills": ["找技能", "技能推荐", "技能搜索", "有什么技能"],
        "pptx": ["做PPT", "写PPT", "演示文稿", "制作演示", "PPT", "ppt"],
        "docx": ["写文档", "文档", "写Word", "Word文档", "word", "doc"],
        "xlsx": ["表格", "Excel", "电子表格", "写表格", "excel"],
        "pdf": ["PDF", "处理PDF", "读取PDF", "PDF文件", "pdf"],
        "playwright-skill": ["playwright", "网页自动化", "浏览器自动化", "网页测试", "浏览器测试"],
    }
    if name in extra:
        triggers.extend(extra[name])
    seen = set()
    ordered = []
    for trig in triggers:
        if trig in seen:
            continue
        seen.add(trig)
        ordered.append(trig)
    return ordered[:6]


def has_scripts_dir(skill_md):
    skill_dir = os.path.dirname(skill_md)
    return os.path.isdir(os.path.join(skill_dir, "scripts"))


def render_skill_file(name, description, triggers, skill_md, script_hint):
    skill_path = os.path.relpath(skill_md, BASE_DIR)
    trigger_list = ", ".join([f'"{t}"' for t in triggers])
    safe_name = _escape_string(name)
    safe_desc = _escape_string(description)
    safe_path = _escape_string(skill_path)
    scripts_dir = _escape_string(os.path.join(os.path.dirname(skill_md), "scripts"))
    if safe_name == "playwright-skill":
        return render_playwright_skill(safe_name, safe_desc, trigger_list, safe_path)
    return f"""import os
import json
import subprocess

SKILL_INFO = {{
    "name": "{safe_name}",
    "description": "{safe_desc}",
    "triggers": [{trigger_list}],
    "action": "{safe_name}",
    "parameters": {{"type": "object", "properties": {{}}}}
}}

SKILL_PATH = "{safe_path}"
SCRIPTS_DIR = "{scripts_dir}"

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
    return "技能指引:" + "\\n" + content

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
        return {{}}
    if isinstance(params, dict):
        return params
    try:
        return json.loads(params)
    except Exception:
        return {{}}
"""


def _escape_string(value):
    return value.replace("\\", "\\\\").replace("\"", "\\\"")


def render_playwright_skill(name, description, trigger_list, skill_path):
    return f"""import os
import json
import re
import subprocess
import tempfile

SKILL_INFO = {{
    "name": "{name}",
    "description": "{description}",
    "triggers": [{trigger_list}],
    "action": "{name}",
    "parameters": {{"type": "object", "properties": {{}}}}
}}

SKILL_PATH = "{skill_path}"
SKILL_DIR = os.path.dirname(SKILL_PATH)

def execute(params: str) -> str:
    payload = _parse_params(params)
    if payload.get("detect_servers"):
        return _detect_servers()
    if payload.get("list_scripts"):
        return _list_scripts()
    url = payload.get("url") or _extract_url(params)
    headless = bool(payload.get("headless", False))
    timeout = payload.get("timeout", 30)
    try:
        timeout = int(timeout)
    except Exception:
        timeout = 30
    if url:
        return _run_playwright(url, headless, timeout)
    return _auto_or_guidance(headless, timeout)

def _detect_servers() -> str:
    try:
        result = subprocess.run(
            ["node", "-e", "require('./lib/helpers').detectDevServers().then(s => console.log(JSON.stringify(s)))"],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        return "服务器探测失败: " + str(exc)
    return result.stdout.strip() or "未发现本地服务"

def _auto_or_guidance(headless: bool, timeout: int) -> str:
    raw = _detect_servers()
    try:
        servers = json.loads(raw)
    except Exception:
        return _read_skill()
    if not servers:
        return "未检测到本地服务，请提供 URL"
    if len(servers) == 1:
        url = servers[0].get("url") or servers[0].get("origin")
        if not url:
            return "检测到服务但缺少 URL，请手动提供"
        return _run_playwright(url, headless, timeout)
    options = "\\n".join(["- " + (entry.get('url') or entry.get('origin')) for entry in servers])
    return "检测到多个本地服务，请选择一个 URL:\\n" + options

def _run_playwright(url: str, headless: bool, timeout: int) -> str:
    script_path = _write_temp_script(url, headless)
    if not script_path:
        return "生成脚本失败"
    if not os.path.exists(os.path.join(SKILL_DIR, "run.js")):
        return "未找到 run.js，请确认 playwright-skill 安装完整"
    if not os.path.isdir(os.path.join(SKILL_DIR, "node_modules")):
        return "Playwright 未安装，请先在 skill 目录执行 npm run setup"
    try:
        result = subprocess.run(
            ["node", "run.js", script_path],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "执行超时，请确认 Playwright 环境已安装"
    except Exception as exc:
        return "执行失败: " + str(exc)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return output or "执行失败，请检查 Playwright 环境"
    return output or "执行完成"

def _write_temp_script(url: str, headless: bool) -> str:
    template = (
        "const {{ chromium }} = require('playwright');\\n"
        "const TARGET_URL = '__URL__';\\n\\n"
        "(async () => {{\\n"
        "  const browser = await chromium.launch({{ headless: __HEADLESS__ }});\\n"
        "  const page = await browser.newPage();\\n"
        "  await page.goto(TARGET_URL, {{ waitUntil: 'networkidle' }});\\n"
        "  await page.screenshot({{ path: '/tmp/playwright-skill.png', fullPage: true }});\\n"
        "  console.log('Screenshot saved to /tmp/playwright-skill.png');\\n"
        "  await browser.close();\\n"
        "}})();\\n"
    )
    template = template.replace("__URL__", url)
    template = template.replace("__HEADLESS__", "true" if headless else "false")
    try:
        fd, path = tempfile.mkstemp(prefix="playwright-test-", suffix=".js")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(template)
        return path
    except Exception:
        return ""

def _list_scripts() -> str:
    scripts_dir = os.path.join(SKILL_DIR, "scripts")
    if not os.path.isdir(scripts_dir):
        return "该技能没有 scripts 目录"
    files = sorted(os.listdir(scripts_dir))
    if not files:
        return "scripts 目录为空"
    return "可用脚本: " + ", ".join(files)

def _read_skill() -> str:
    if not os.path.exists(SKILL_PATH):
        return "未找到技能文件，请确认 outer_skills 已同步"
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()
    content = _strip_frontmatter(content)
    if len(content) > 1200:
        content = content[:1200] + "..."
    return "技能指引:" + "\\n" + content

def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return content
    return parts[2].strip()

def _parse_params(params):
    if not params:
        return {{}}
    if isinstance(params, dict):
        return params
    try:
        return json.loads(params)
    except Exception:
        return {{}}

def _extract_url(text):
    if not text:
        return ""
    match = re.search(r"https?://\S+", str(text))
    if match:
        return match.group(0)
    return ""
"""


if __name__ == "__main__":
    main()

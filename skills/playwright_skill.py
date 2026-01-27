import os
import json
import re
import subprocess
import tempfile

SKILL_INFO = {
    "name": "playwright-skill",
    "description": "Complete browser automation with Playwright. Auto-detects dev servers, writes clean test scripts to /tmp. Test pages, fill forms, take screenshots, check responsive design, validate UX, test login flows, check links, automate any browser task. Use when user wants to test websites, automate browser interactions, validate web functionality, or perform any browser-based testing.",
    "triggers": ["playwrightskill", "playwright skill", "playwright-skill", "playwright", "网页自动化", "浏览器自动化"],
    "action": "playwright-skill",
    "parameters": {"type": "object", "properties": {}}
}

SKILL_PATH = "outer_skills/playwright-skill/SKILL.md"
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
    options = "\n".join(["- " + (entry.get('url') or entry.get('origin')) for entry in servers])
    return "检测到多个本地服务，请选择一个 URL:\n" + options

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
        "const { chromium } = require('playwright');\n"
        "const TARGET_URL = '__URL__';\n\n"
        "(async () => {\n"
        "  const browser = await chromium.launch({ headless: __HEADLESS__ });\n"
        "  const page = await browser.newPage();\n"
        "  await page.goto(TARGET_URL, { waitUntil: 'networkidle' });\n"
        "  await page.screenshot({ path: '/tmp/playwright-skill.png', fullPage: true });\n"
        "  console.log('Screenshot saved to /tmp/playwright-skill.png');\n"
        "  await browser.close();\n"
        "})();\n"
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
    return "技能指引:" + "\n" + content

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

def _extract_url(text):
    if not text:
        return ""
    match = re.search(r"https?://\S+", str(text))
    if match:
        return match.group(0)
    return ""

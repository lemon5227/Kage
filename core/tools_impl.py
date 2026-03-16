"""
核心工具实现

包含 7 个核心工具的具体实现：
- tavily_search: 网页搜索
- web_fetch: 网页内容抓取
- exec_command: Shell 命令执行
- find_skills: 技能文件搜索
- memory_search: 记忆检索
- proactive_agent: 技能文件创建
- open_url: 浏览器打开 URL
"""

import os
import json
import subprocess
import urllib.request
import urllib.parse
import urllib.error as urllib_error
import re
import logging
import shutil
import textwrap
from html.parser import HTMLParser
import time
import html

from core.undo_log import UndoLog, _move_to_trash
from core.system_control import system_control as _system_control, system_capabilities as _system_capabilities

logger = logging.getLogger(__name__)

# 常量
MAX_OUTPUT_LENGTH = 5000
TRUNCATION_MARKER = "[输出已截断]"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _ensure_node_tools() -> tuple[bool, str]:
    """Return (ok, message)."""
    if shutil.which("node") is None or shutil.which("npx") is None:
        return False, (
            "未检测到 Node.js/npx。技能生态能力需要 Node.js。"
            "macOS 可用: brew install node (或使用 nvm)。"
        )
    return True, ""


def _run_npx(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run `npx` with best-effort stable flags."""
    env = os.environ.copy()
    # Reduce noise and avoid telemetry where possible.
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


def _parse_skills_find_output(text: str, max_results: int = 5) -> list[dict]:
    """Parse `npx skills find <query>` output.

    Expected lines like:
      vercel-labs/agent-skills@vercel-react-best-practices
      └ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
    """
    out: list[dict] = []
    seen: set[str] = set()
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines) and len(out) < max_results:
        line = lines[i].strip()
        m = re.match(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+)$", line)
        if m:
            repo = m.group(1)
            skill = m.group(2)
            key = f"{repo}@{skill}"
            url = ""
            # Next line may contain skills.sh URL
            if i + 1 < len(lines):
                m2 = re.search(r"https?://skills\.sh/\S+", lines[i + 1])
                if m2:
                    url = m2.group(0)
            if key not in seen:
                seen.add(key)
                out.append({
                    "repo": repo,
                    "skill": skill,
                    "ref": key,
                    "url": url,
                })
            i += 2
            continue
        i += 1
    return out


# ============== HTML 文本提取 ==============

class HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本"""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._skip_tags = {'script', 'style', 'head', 'meta', 'link', 'noscript'}
        self._current_skip = False
    
    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._skip_tags:
            self._current_skip = True
    
    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags:
            self._current_skip = False
    
    def handle_data(self, data):
        if not self._current_skip:
            text = data.strip()
            if text:
                self.text_parts.append(text)
    
    def get_text(self) -> str:
        return ' '.join(self.text_parts)


def _strip_html_tags(html: str) -> str:
    """从 HTML 中提取纯文本，去除标签、脚本、样式。"""
    try:
        extractor = HTMLTextExtractor()
        extractor.feed(html)
        return extractor.get_text()
    except Exception:
        # 回退：简单正则去除标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        return ' '.join(text.split())


def _truncate_output(text: str, max_length: int = MAX_OUTPUT_LENGTH) -> str:
    """截断输出并添加标记。"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


# ============== tavily_search ==============

def _tavily_api_search(query: str, max_results: int, api_key: str) -> str:
    """使用 Tavily API 搜索。"""
    try:
        url = "https://api.tavily.com/search"
        data = json.dumps({
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        }).encode('utf-8')
        
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        results = []
        for item in result.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:200],
            })
        
        return json.dumps({"results": results}, ensure_ascii=False)
        
    except urllib_error.URLError as e:
        if hasattr(e, 'reason') and 'timed out' in str(e.reason).lower():
            return json.dumps({"error": "Timeout", "message": "搜索超时"}, ensure_ascii=False)
        return json.dumps({"error": "NetworkError", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "NetworkError", "message": str(e)}, ensure_ascii=False)


def _duckduckgo_fallback(query: str, max_results: int) -> str:
    """使用 DuckDuckGo HTML 搜索作为回退。"""
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
        
        # 简单解析 DuckDuckGo HTML 结果
        results = []
        # 匹配结果链接和标题
        pattern = r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)
        
        for url, title in matches[:max_results]:
            # DuckDuckGo 的 URL 是重定向链接，需要解码
            if 'uddg=' in url:
                try:
                    actual_url = urllib.parse.unquote(url.split('uddg=')[1].split('&')[0])
                except:
                    actual_url = url
            else:
                actual_url = url
            
            results.append({
                "title": title.strip(),
                "url": actual_url,
                "snippet": "",
            })
        
        if not results:
            return json.dumps({"results": [], "message": "未找到结果"}, ensure_ascii=False)
        
        return json.dumps({"results": results}, ensure_ascii=False)
        
    except urllib_error.URLError as e:
        if hasattr(e, 'reason') and 'timed out' in str(e.reason).lower():
            return json.dumps({"error": "Timeout", "message": "搜索超时"}, ensure_ascii=False)
        return json.dumps({"error": "NetworkError", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "NetworkError", "message": str(e)}, ensure_ascii=False)


def parse_duckduckgo_html(html_text: str, max_results: int = 5) -> list[tuple[str, str]]:
    """Parse DuckDuckGo HTML result links.

    Returns list of (title, url). Used by tests; keep dependency-free.
    """
    text = str(html_text or "")
    max_results = max(1, min(20, int(max_results or 5)))
    results: list[tuple[str, str]] = []

    pattern = re.compile(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE)
    for m in pattern.finditer(text):
        href = html.unescape(m.group(1))
        title = html.unescape(re.sub(r"<.*?>", "", m.group(2))).strip()
        if not href or not title:
            continue
        if href.startswith("/l/?uddg=") or "uddg=" in href:
            try:
                # Handle both absolute and relative redirect urls.
                qs = urllib.parse.urlparse(href).query
                if not qs and "uddg=" in href:
                    qs = href.split("?", 1)[1] if "?" in href else href
                params = urllib.parse.parse_qs(qs)
                uddg = params.get("uddg", [""])[0]
                if uddg:
                    href = urllib.parse.unquote(uddg)
            except Exception:
                pass
        results.append((title, href))
        if len(results) >= max_results:
            break
    return results


def tavily_search(query: str, max_results: int = 5) -> str:
    """搜索网页信息。优先 Tavily API，回退 DuckDuckGo。"""
    max_results = max(1, min(10, max_results))
    api_key = os.environ.get("TAVILY_API_KEY", "")
    
    if api_key:
        return _tavily_api_search(query, max_results, api_key)
    return _duckduckgo_fallback(query, max_results)


# ============== web_fetch ==============

def web_fetch(url: str) -> str:
    """获取网页内容，提取纯文本。"""
    if not url or not url.strip():
        return json.dumps({"success": False, "error": "InvalidURL", "message": "URL 为空", "content": ""}, ensure_ascii=False)
    
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    # 验证 URL 格式
    try:
        parsed = urllib.parse.urlparse(url)
        if not parsed.netloc:
            return json.dumps({"success": False, "error": "InvalidURL", "message": "URL 格式错误", "content": ""}, ensure_ascii=False)
    except Exception:
        return json.dumps({"success": False, "error": "InvalidURL", "message": "URL 格式错误", "content": ""}, ensure_ascii=False)
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        
        with urllib.request.urlopen(req, timeout=15) as response:
            # 检查状态码
            if response.status != 200:
                return json.dumps({
                    "success": False,
                    "error": "HTTPError",
                    "status_code": response.status,
                    "message": f"HTTP {response.status}",
                    "content": "",
                }, ensure_ascii=False)
            
            html = response.read().decode('utf-8', errors='ignore')
        
        # 提取纯文本
        text = _strip_html_tags(html)
        text = _truncate_output(text, MAX_OUTPUT_LENGTH)
        
        return json.dumps({"success": True, "content": text, "url": url}, ensure_ascii=False)
        
    except urllib_error.HTTPError as e:
        return json.dumps({
            "success": False,
            "error": "HTTPError",
            "status_code": e.code,
            "message": str(e.reason),
            "content": "",
        }, ensure_ascii=False)
    except urllib_error.URLError as e:
        if hasattr(e, 'reason') and 'timed out' in str(e.reason).lower():
            return json.dumps({"success": False, "error": "Timeout", "message": "请求超时", "content": ""}, ensure_ascii=False)
        return json.dumps({"success": False, "error": "NetworkError", "message": str(e.reason), "content": ""}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": "NetworkError", "message": str(e), "content": ""}, ensure_ascii=False)


# ============== exec_command ==============

def exec_command(command: str, timeout: int = 30) -> str:
    """执行 shell 命令。"""
    timeout = max(1, min(120, timeout))
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
        
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        
        # 截断输出
        if len(stdout) > MAX_OUTPUT_LENGTH:
            stdout = stdout[:MAX_OUTPUT_LENGTH - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
        if len(stderr) > MAX_OUTPUT_LENGTH:
            stderr = stderr[:MAX_OUTPUT_LENGTH - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
        
        return json.dumps({
            "stdout": stdout,
            "stderr": stderr,
            "return_code": result.returncode,
        }, ensure_ascii=False)
        
    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": "Timeout",
            "message": "命令执行超时"
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "error": "ExecutionError",
            "message": str(e)
        }, ensure_ascii=False)


# ============== open_url ==============

def open_url(url: str) -> str:
    """在默认浏览器中打开 URL。"""
    if not url or not url.strip():
        return json.dumps({"error": "InvalidURL", "message": "URL 为空"}, ensure_ascii=False)
    
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    try:
        # macOS 使用 open 命令
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            timeout=5,
            text=True,
        )
        
        if result.returncode == 0:
            return json.dumps({"success": True, "url": url}, ensure_ascii=False)
        else:
            return json.dumps({
                "error": "OpenError",
                "message": result.stderr or "无法打开 URL"
            }, ensure_ascii=False)
            
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Timeout", "message": "打开超时"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "OpenError", "message": str(e)}, ensure_ascii=False)


# ============== find_skills ==============

def find_skills(query: str, max_results: int = 5, skills_dir: str = "skills") -> str:
    """Search locally available skills (SKILL.md).

    Scans multiple sources so that skills installed via `npx skills add -g -a opencode`
    are discoverable.
    """
    from core.skill_parser import default_skill_sources, scan_skill_sources, scan_skills_directory
    
    max_results = max(1, min(5, max_results))
    
    # Backward compatibility: allow explicit directory.
    if skills_dir and skills_dir != "skills":
        skills = scan_skills_directory(skills_dir)
    else:
        skills = scan_skill_sources(default_skill_sources())
    
    if not skills:
        return json.dumps({
            "results": [],
            "message": "无可用技能"
        }, ensure_ascii=False)
    
    # 简单关键词匹配排序
    query_lower = query.lower()
    query_words = set(query_lower.split())
    
    def score_skill(skill):
        """计算技能与查询的匹配分数。"""
        text = f"{skill.title} {skill.description}".lower()
        score = 0
        # 完整查询匹配
        if query_lower in text:
            score += 10
        # 单词匹配
        for word in query_words:
            if word in text:
                score += 1
        return score
    
    # 按分数排序
    scored_skills = [(skill, score_skill(skill)) for skill in skills]
    scored_skills.sort(key=lambda x: x[1], reverse=True)
    
    # 过滤掉分数为 0 的结果
    results = []
    for skill, score in scored_skills[:max_results]:
        if score > 0:
            results.append({
                "filename": skill.filename,
                "title": skill.title,
                "description": skill.description[:200],
            })
    
    if not results:
        # 如果没有匹配，返回前几个技能
        for skill in skills[:max_results]:
            results.append({
                "filename": skill.filename,
                "title": skill.title,
                "description": skill.description[:200],
            })
    
    return json.dumps({"results": results}, ensure_ascii=False)


# ============== memory_search ==============

def memory_search(query: str, n_results: int = 5, memory_system=None) -> str:
    """搜索记忆系统。"""
    if memory_system is None:
        return json.dumps({
            "results": [],
            "message": "记忆系统未初始化"
        }, ensure_ascii=False)
    
    try:
        memories = memory_system.recall(query, n_results=n_results)
        
        results = []
        for mem in memories:
            results.append({
                "content": mem.get("content", ""),
                "importance": mem.get("importance", 0),
                "timestamp": mem.get("timestamp", ""),
            })
        
        return json.dumps({"results": results}, ensure_ascii=False)
        
    except Exception as e:
        logger.warning("记忆检索失败: %s", e)
        return json.dumps({
            "results": [],
            "error": str(e)
        }, ensure_ascii=False)


# ============== proactive_agent ==============

def proactive_agent(skill_name: str, description: str, steps: str = "", skills_dir: str = "skills") -> str:
    """创建新的 SKILL.md 技能文件。"""
    if not skill_name or not skill_name.strip():
        return json.dumps({"error": "InvalidInput", "message": "技能名称为空"}, ensure_ascii=False)
    if not description or not description.strip():
        return json.dumps({"error": "InvalidInput", "message": "技能描述为空"}, ensure_ascii=False)
    
    # 清理技能名称，生成文件名
    safe_name = re.sub(r'[^\w\-]', '_', skill_name.strip().lower())
    
    # 确保 skills 目录存在
    os.makedirs(skills_dir, exist_ok=True)
    
    # 处理文件名冲突
    base_filename = f"{safe_name}.md"
    filepath = os.path.join(skills_dir, base_filename)
    
    counter = 2
    while os.path.exists(filepath):
        base_filename = f"{safe_name}_{counter}.md"
        filepath = os.path.join(skills_dir, base_filename)
        counter += 1
    
    # 生成 SKILL.md 内容
    content = f"""# {skill_name.strip()}

## 描述

{description.strip()}

## 使用场景

- 当用户需要 {skill_name.strip()} 时使用

## 执行步骤

{steps.strip() if steps else "1. 根据描述执行相应操作"}

## 注意事项

- 请根据实际情况调整执行步骤
"""
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        return json.dumps({
            "success": True,
            "filename": base_filename,
            "path": filepath,
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            "error": "WriteError",
            "message": str(e)
        }, ensure_ascii=False)


# ============== skills.sh ecosystem (npx skills) ==============


def skills_find_remote(query: str, max_results: int = 5) -> str:
    """Search the skills ecosystem via `npx skills find`.

    Returns JSON: { results: [{repo, skill, ref, url, install_cmd}] }
    """
    q = str(query or "").strip()
    if not q:
        return json.dumps({"results": [], "error": "InvalidInput", "message": "query 为空"}, ensure_ascii=False)
    max_results = max(1, min(10, int(max_results or 5)))

    ok, msg = _ensure_node_tools()
    if not ok:
        return json.dumps({"results": [], "error": "MissingDependency", "message": msg}, ensure_ascii=False)

    # Keyword mode: `npx skills find <query>`
    code, stdout, stderr = _run_npx(["skills", "find", q], timeout=30)
    combined = (stdout + "\n" + stderr).strip()
    if code != 0 and not combined:
        return json.dumps({"results": [], "error": "ExecutionError", "message": f"npx skills find failed ({code})"}, ensure_ascii=False)

    results = _parse_skills_find_output(combined, max_results=max_results)
    for r in results:
        r["install_cmd"] = f"npx skills add https://github.com/{r['repo']} --skill {r['skill']} -g -a opencode -y"
    return json.dumps({"results": results}, ensure_ascii=False)


def skills_install(repo: str, skill: str, global_install: bool = True, agent: str = "opencode") -> str:
    """Install a skill using the Skills CLI.

    Per project policy: installs discovered from skills.sh should be non-interactive.
    This tool does NOT attempt to execute arbitrary code; it only installs SKILL.md.
    """
    ok, msg = _ensure_node_tools()
    if not ok:
        return json.dumps({"success": False, "error": "MissingDependency", "message": msg}, ensure_ascii=False)

    repo_s = str(repo or "").strip()
    skill_s = str(skill or "").strip()
    if not repo_s or not skill_s:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "repo/skill 不能为空"}, ensure_ascii=False)

    # Normalize repo input. For safety, only allow GitHub repos/URLs.
    if repo_s.startswith("https://github.com/"):
        repo_arg = repo_s
    elif re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo_s):
        repo_arg = f"https://github.com/{repo_s}"
    else:
        return json.dumps(
            {
                "success": False,
                "error": "InvalidRepo",
                "message": "repo 仅支持 GitHub: owner/repo 或 https://github.com/owner/repo",
            },
            ensure_ascii=False,
        )

    args = ["skills", "add", repo_arg, "--skill", skill_s, "-y"]
    if bool(global_install):
        args.insert(3, "-g")
    if agent:
        args.extend(["-a", str(agent)])

    code, stdout, stderr = _run_npx(args, timeout=120)
    combined = (stdout + "\n" + stderr).strip()
    if code != 0:
        return json.dumps({"success": False, "error": "InstallFailed", "message": _truncate_output(combined, 2000)}, ensure_ascii=False)
    return json.dumps({"success": True, "message": "installed", "output": _truncate_output(combined, 2000)}, ensure_ascii=False)


def skills_list(global_install: bool = True, agent: str = "opencode") -> str:
    """List installed skills via `npx skills list`."""
    ok, msg = _ensure_node_tools()
    if not ok:
        return json.dumps({"error": "MissingDependency", "message": msg}, ensure_ascii=False)
    args = ["skills", "list"]
    if bool(global_install):
        args.append("-g")
    if agent:
        args.extend(["-a", str(agent)])
    code, stdout, stderr = _run_npx(args, timeout=30)
    combined = (stdout + "\n" + stderr).strip()
    if code != 0:
        return json.dumps({"error": "ExecutionError", "message": _truncate_output(combined, 2000)}, ensure_ascii=False)
    return json.dumps({"output": _truncate_output(combined, 5000)}, ensure_ascii=False)


def skills_read(skill_name: str, workspace_dir: str = "~/.kage") -> str:
    """Read a locally available SKILL.md by name (frontmatter name).

    Searches multiple skill sources:
    - ./outer_skills
    - ./skills
    - ~/.kage/skills
    - ~/.config/opencode/skills
    """
    name = str(skill_name or "").strip()
    if not name:
        return json.dumps({"error": "InvalidInput", "message": "skill_name 为空"}, ensure_ascii=False)

    from core.skill_parser import default_skill_sources, scan_skill_sources

    sources = default_skill_sources(workspace_dir=workspace_dir)
    infos = scan_skill_sources(sources)
    for info in infos:
        if info.name == name:
            return json.dumps({
                "name": info.name,
                "title": info.title,
                "description": info.description,
                "content": _truncate_output(info.full_content, 8000),
            }, ensure_ascii=False)
    return json.dumps({"error": "NotFound", "message": f"未找到 skill: {name}"}, ensure_ascii=False)


# ============== filesystem helpers (undoable) ==============


def fs_move(src: str, dest_dir: str, workspace_dir: str = "~/.kage") -> str:
    """Move a file/dir into dest_dir (non-destructive). Records undo."""
    s = str(src or "").strip()
    d = str(dest_dir or "").strip()
    if not s or not d:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "src/dest_dir 不能为空"}, ensure_ascii=False)
    s = os.path.expanduser(s)
    d = os.path.expanduser(d)
    if not os.path.exists(s):
        return json.dumps({"success": False, "error": "NotFound", "message": f"未找到: {s}"}, ensure_ascii=False)
    os.makedirs(d, exist_ok=True)
    base = os.path.basename(s.rstrip(os.sep))
    target = os.path.join(d, base)
    if os.path.exists(target):
        # avoid overwrite
        target = os.path.join(d, f"{base}.{int(time.time())}")
    undo = UndoLog(workspace_dir=workspace_dir)
    entry_id = undo.append({
        "type": "fs_move",
        "ops": [{"op": "move", "src": s, "dst": target}],
    })
    shutil.move(s, target)
    return json.dumps({"success": True, "moved": {"from": s, "to": target}, "undo_id": entry_id}, ensure_ascii=False)


def fs_rename(path: str, new_name: str, workspace_dir: str = "~/.kage") -> str:
    """Rename a file/dir (non-destructive). Records undo."""
    p = str(path or "").strip()
    nn = str(new_name or "").strip()
    if not p or not nn:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "path/new_name 不能为空"}, ensure_ascii=False)
    p = os.path.expanduser(p)
    if not os.path.exists(p):
        return json.dumps({"success": False, "error": "NotFound", "message": f"未找到: {p}"}, ensure_ascii=False)
    parent = os.path.dirname(p)
    target = os.path.join(parent, nn)
    if os.path.exists(target):
        return json.dumps({"success": False, "error": "Exists", "message": f"目标已存在: {target}"}, ensure_ascii=False)
    undo = UndoLog(workspace_dir=workspace_dir)
    entry_id = undo.append({
        "type": "fs_rename",
        "ops": [{"op": "move", "src": p, "dst": target}],
    })
    shutil.move(p, target)
    return json.dumps({"success": True, "renamed": {"from": p, "to": target}, "undo_id": entry_id}, ensure_ascii=False)


def fs_write(path: str, content: str, workspace_dir: str = "~/.kage") -> str:
    """Write text to a file.

    Default behavior is undoable: if file exists, backup is created before overwrite.
    """
    p = str(path or "").strip()
    if not p:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "path 不能为空"}, ensure_ascii=False)
    p = os.path.expanduser(p)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    undo = UndoLog(workspace_dir=workspace_dir)

    ops = []
    if os.path.exists(p):
        backup_dir = os.path.join(os.path.expanduser(workspace_dir), "undo", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"{os.path.basename(p)}.{int(time.time())}.bak")
        shutil.copy2(p, backup_path)
        ops.append({"op": "restore", "path": p, "backup": backup_path})
    else:
        ops.append({"op": "created", "path": p})

    entry_id = undo.append({"type": "fs_write", "ops": ops})
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(content or ""))
    return json.dumps({"success": True, "written": p, "undo_id": entry_id}, ensure_ascii=False)


def fs_trash(path: str, workspace_dir: str = "~/.kage") -> str:
    """Move file/dir to Trash (recoverable). Records undo.

    This is treated as "deletion" (user-defined dangerous op).
    """
    p = str(path or "").strip()
    if not p:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "path 不能为空"}, ensure_ascii=False)
    p = os.path.expanduser(p)
    if not os.path.exists(p):
        return json.dumps({"success": False, "error": "NotFound", "message": f"未找到: {p}"}, ensure_ascii=False)

    undo = UndoLog(workspace_dir=workspace_dir)
    trashed = _move_to_trash(p)
    entry_id = undo.append({
        "type": "fs_trash",
        "ops": [{"op": "untrash", "original": p, "trashed": trashed}],
    })
    return json.dumps({"success": True, "trashed": trashed, "undo_id": entry_id}, ensure_ascii=False)


def fs_undo_last(workspace_dir: str = "~/.kage") -> str:
    """Undo the last recorded filesystem operation."""
    undo = UndoLog(workspace_dir=workspace_dir)
    return json.dumps(undo.undo_last(), ensure_ascii=False)


def fs_search(query: str, kind: str = "any", max_results: int = 20, scope: list[str] | None = None) -> str:
    """Search files/folders using Spotlight (macOS).

    This is the main primitive for "full disk" discovery.

    Args:
        query: name keyword
        kind: any|file|dir
        max_results: cap results
        scope: optional list of directories to restrict search
    """
    q = str(query or "").strip()
    if not q:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "query 为空"}, ensure_ascii=False)
    k = str(kind or "any").strip().lower()
    if k not in ("any", "file", "dir"):
        k = "any"
    limit = max(1, min(200, int(max_results or 20)))

    # Build mdfind command.
    cmd = ["mdfind", "-name", q]
    if scope:
        # mdfind supports only one -onlyin, so run per scope and merge.
        scopes = [os.path.expanduser(str(s)) for s in scope if str(s).strip()]
    else:
        scopes = []

    results: list[str] = []
    seen: set[str] = set()

    def _run(one_scope: str | None):
        args = list(cmd)
        if one_scope:
            args = ["mdfind", "-onlyin", one_scope, "-name", q]
        try:
            out = subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return []
        paths = [line.strip() for line in (out or "").splitlines() if line.strip()]
        return paths

    batches = []
    if scopes:
        for s in scopes:
            if os.path.isdir(s):
                batches.append(_run(s))
    else:
        batches.append(_run(None))

    for batch in batches:
        for p in batch:
            if p in seen:
                continue
            seen.add(p)
            if k == "dir" and not os.path.isdir(p):
                continue
            if k == "file" and not os.path.isfile(p):
                continue
            results.append(p)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return json.dumps({"success": True, "results": results}, ensure_ascii=False)


def fs_preview(ops: list[dict]) -> str:
    """Preview a generic file operation plan.

    This is intentionally simple: returns a compact summary and flags potential risks.
    """
    if not isinstance(ops, list) or not ops:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "ops 为空"}, ensure_ascii=False)

    summary = []
    has_trash = False
    for op in ops[:200]:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op") or "").strip().lower()
        if kind == "move":
            summary.append({"op": "move", "src": op.get("src"), "dest_dir": op.get("dest_dir")})
        elif kind == "rename":
            summary.append({"op": "rename", "path": op.get("path"), "new_name": op.get("new_name")})
        elif kind == "write":
            content = str(op.get("content") or "")
            summary.append({"op": "write", "path": op.get("path"), "bytes": len(content.encode("utf-8"))})
        elif kind == "trash":
            has_trash = True
            summary.append({"op": "trash", "path": op.get("path")})

    return json.dumps({"success": True, "has_trash": has_trash, "ops": summary}, ensure_ascii=False)


def fs_apply(ops: list[dict], workspace_dir: str = "~/.kage") -> str:
    """Apply a generic file operation plan (undoable).

    Supported ops:
    - move: {src, dest_dir}
    - rename: {path, new_name}
    - write: {path, content}
    - trash: {path} (deletion-like; should be confirmation-gated by ToolExecutor)
    """
    if not isinstance(ops, list) or not ops:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "ops 为空"}, ensure_ascii=False)

    undo = UndoLog(workspace_dir=workspace_dir)
    undo_ops = []
    applied = []

    for op in ops[:200]:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op") or "").strip().lower()
        if kind == "move":
            src = str(op.get("src") or "").strip()
            dest_dir = str(op.get("dest_dir") or "").strip()
            if not src or not dest_dir:
                continue
            s = os.path.expanduser(src)
            d = os.path.expanduser(dest_dir)
            if not os.path.exists(s):
                applied.append({"op": "move", "status": "skipped", "reason": "not_found", "src": s})
                continue
            os.makedirs(d, exist_ok=True)
            base = os.path.basename(s.rstrip(os.sep))
            target = os.path.join(d, base)
            if os.path.exists(target):
                target = os.path.join(d, f"{base}.{int(time.time())}")
            shutil.move(s, target)
            undo_ops.append({"op": "move", "src": s, "dst": target})
            applied.append({"op": "move", "status": "ok", "from": s, "to": target})

        elif kind == "rename":
            path = str(op.get("path") or "").strip()
            new_name = str(op.get("new_name") or "").strip()
            if not path or not new_name:
                continue
            p = os.path.expanduser(path)
            if not os.path.exists(p):
                applied.append({"op": "rename", "status": "skipped", "reason": "not_found", "path": p})
                continue
            parent = os.path.dirname(p)
            target = os.path.join(parent, new_name)
            if os.path.exists(target):
                applied.append({"op": "rename", "status": "skipped", "reason": "exists", "to": target})
                continue
            shutil.move(p, target)
            undo_ops.append({"op": "move", "src": p, "dst": target})
            applied.append({"op": "rename", "status": "ok", "from": p, "to": target})

        elif kind == "write":
            path = str(op.get("path") or "").strip()
            content = str(op.get("content") or "")
            if not path:
                continue
            p = os.path.expanduser(path)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            if os.path.exists(p):
                backup_dir = os.path.join(os.path.expanduser(workspace_dir), "undo", "backups")
                os.makedirs(backup_dir, exist_ok=True)
                backup_path = os.path.join(backup_dir, f"{os.path.basename(p)}.{int(time.time())}.bak")
                shutil.copy2(p, backup_path)
                undo_ops.append({"op": "restore", "path": p, "backup": backup_path})
            else:
                undo_ops.append({"op": "created", "path": p})
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            applied.append({"op": "write", "status": "ok", "path": p})

        elif kind == "trash":
            path = str(op.get("path") or "").strip()
            if not path:
                continue
            p = os.path.expanduser(path)
            if not os.path.exists(p):
                applied.append({"op": "trash", "status": "skipped", "reason": "not_found", "path": p})
                continue
            trashed = _move_to_trash(p)
            undo_ops.append({"op": "untrash", "original": p, "trashed": trashed})
            applied.append({"op": "trash", "status": "ok", "path": p, "trashed": trashed})

    undo_id = undo.append({"type": "fs_apply", "ops": undo_ops})
    return json.dumps({"success": True, "undo_id": undo_id, "applied": applied}, ensure_ascii=False)


def system_control(target: str, action: str, value: str = "") -> str:
    return _system_control(target=target, action=action, value=value)


def system_capabilities() -> str:
    return _system_capabilities()


def get_time() -> str:
    """Return current local time as a string."""
    try:
        import datetime

        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def open_app(app_name: str) -> str:
    """Open an application on macOS."""
    name = str(app_name or "").strip()
    if not name:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "app_name 为空"}, ensure_ascii=False)

    # Basic alias normalization (keep small; more belongs in skills/prefs).
    alias = {
        "网易云": "NeteaseMusic",
        "网易云音乐": "NeteaseMusic",
        "微信": "WeChat",
        "浏览器": "Safari",
        "safari": "Safari",
        "系统设置": "System Settings",
        "设置": "System Settings",
        "终端": "Terminal",
    }
    norm = alias.get(name.lower(), name)

    try:
        proc = subprocess.run(["open", "-a", norm], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return json.dumps({"success": False, "error": "ExecutionError", "message": msg or "open failed"}, ensure_ascii=False)
    return json.dumps({"success": True, "message": f"opened {norm}"}, ensure_ascii=False)


def open_website(site: str) -> str:
    """Open a website by name/url/domain (best-effort)."""
    s = str(site or "").strip()
    if not s:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "site 为空"}, ensure_ascii=False)

    m = re.search(r"https?://\S+", s)
    if m:
        return open_url(m.group(0))
    m = re.search(r"\b([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b", s)
    if m:
        return open_url("https://" + m.group(0))

    query = s if "官网" in s else f"{s} 官网"
    try:
        payload = json.loads(tavily_search(query, max_results=3))
        items = payload.get("results") if isinstance(payload, dict) else None
    except Exception:
        items = None
    if isinstance(items, list) and items:
        url = str((items[0] or {}).get("url") or "").strip()
        if url:
            return open_url(url)
    return json.dumps({"success": False, "error": "NotFound", "message": "没有找到可打开的网站"}, ensure_ascii=False)


def smart_search(query: str, max_results: int = 5, strategy: str = "auto") -> str:
    """Smart search wrapper (legacy-compatible output).

    Notes:
    - This keeps backward-compatible `results` payload for existing callers.
    - New code should prefer `search(...)` primitive for unified schema.
    """
    q = str(query or "")
    src = str(strategy or "auto").strip().lower() or "auto"
    if src not in ("auto", "web", "youtube", "bilibili"):
        src = "auto"
    low = q.lower()
    is_video_intent = ("视频" in q) or any(
        k in low for k in ("youtube", "youtuber", "video", "bilibili")
    ) or any(k in q for k in ("b站", "哔哩", "哔哩哔哩"))
    if src == "auto" and is_video_intent:
        if any(k in q for k in ("b站", "哔哩", "哔哩哔哩")) or "bilibili" in low:
            src = "bilibili"
        else:
            # Default for creator/video lookup: YouTube.
            src = "youtube"

    sort = "relevance"
    if any(k in q for k in ("最新", "刚发", "最近", "本周", "今日")) or any(
        k in low for k in ("latest", "new", "recent", "today")
    ):
        sort = "latest"
    # Return unified payload while preserving legacy `results` field.
    return search(query=q, source=src, sort=sort, max_results=int(max_results or 5), filters={})


def _normalize_search_items(raw_payload: dict, source: str, provider: str) -> list[dict]:
    """Normalize provider-specific payload into unified search items."""
    items = raw_payload.get("results") if isinstance(raw_payload, dict) else None
    if not isinstance(items, list):
        return []

    out: list[dict] = []
    for idx, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("url") or "").strip()
        snippet = str(it.get("snippet") or it.get("content") or "").strip()
        if not url and not title:
            continue
        out.append(
            {
                "id": str(idx),
                "title": title,
                "url": url,
                "domain": urllib.parse.urlparse(url).netloc.lower() if url else "",
                "snippet": snippet,
                "content": snippet,
                "source": source,
                "provider": provider,
                "published_at": str(it.get("published_at") or "").strip(),
            }
        )
    return out


def _tokenize_query(q: str) -> list[str]:
    text = str(q or "").lower().strip()
    if not text:
        return []
    # Keep simple and dependency-free.
    parts = re.split(r"\s+|[，,。.!！？?;；:\-_/()\[\]{}]+", text)
    return [p for p in parts if p and len(p) >= 2]


def _is_video_intent_query(q: str) -> bool:
    s = str(q or "")
    low = s.lower()
    return ("视频" in s) or any(
        k in low for k in ("youtube", "youtuber", "video", "bilibili")
    ) or any(k in s for k in ("b站", "哔哩", "哔哩哔哩"))


def _extract_video_subject(query: str) -> str:
    """Extract subject text from a video-intent query without splitting names.

    Keep original contiguous text as much as possible, only remove common
    request wrappers like '帮我找' and trailing intent words like '最新视频'.
    """
    q = str(query or "").strip()
    if not q:
        return ""
    q = q.strip(" ，,。.!！？?；;:：")

    q = re.sub(
        r"[，,\s]*(然后|再|并且|并|顺便)\s*(把|帮我)?\s*(它|这个|结果|视频|链接)?\s*(打开|点开|播放|播一下|放一下)(吧|一下)?[。.!！？?]*\s*$",
        "",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"[，,\s]*(把|帮我)?\s*(它|这个|结果|视频|链接)?\s*(打开|点开|播放|播一下|放一下)(吧|一下)?[。.!！？?]*\s*$", "", q, flags=re.IGNORECASE)
    q = re.sub(r"[，,\s]*(然后|再|并且|并|顺便)\s*打开[。.!！？?]*\s*$", "", q, flags=re.IGNORECASE)

    q = re.sub(r"^(帮我|请|麻烦|请帮我|我想|我想看|帮忙)\s*", "", q)
    q = re.sub(r"^(找|搜|搜索|查|看)(一下|下)?\s*", "", q)

    # Remove trailing intent wrappers but keep the core subject contiguous.
    q = re.sub(r"(在)?\s*(youtube|油管|bilibili|b站|哔哩哔哩)\s*(上)?\s*(的)?\s*$", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s*(的)?\s*(最新|最近|刚发|本周|今日)?\s*(视频|频道|直播)\s*$", "", q)
    q = q.strip(" ，,。.!！？?；;:：")
    return q


def _video_query_variants(query: str) -> list[str]:
    """Build retry variants for video query while preserving user phrase first."""
    base = str(query or "").strip()
    if not base:
        return []
    out = [base]
    if not _is_video_intent_query(base):
        return out

    subject = _extract_video_subject(base)
    if subject and subject not in out:
        out.append(subject)
    if subject:
        quoted = f'"{subject}"'
        if quoted not in out:
            out.append(quoted)
    return out


def _score_item(item: dict, tokens: list[str], source: str, sort: str) -> float:
    title = str(item.get("title") or "").lower()
    snippet = str(item.get("snippet") or "").lower()
    domain = str(item.get("domain") or "").lower()
    url = str(item.get("url") or "").lower()
    published = str(item.get("published_at") or "").lower()

    score = 0.0

    # Query token match
    for t in tokens:
        if t in title:
            score += 2.0
        if t in snippet:
            score += 1.0

    # Source-specific preferences
    if source == "youtube":
        if "youtube.com" in domain or "youtu.be" in domain:
            score += 3.0
        if "/watch" in url or "youtu.be/" in url:
            score += 2.0
    elif source == "bilibili":
        if "bilibili.com" in domain:
            score += 3.0
        if "/video/" in url:
            score += 2.0
    elif source == "web":
        # Minor bonus for non-empty domains.
        if domain:
            score += 0.3

    # "latest" preference
    if str(sort or "").lower() == "latest":
        if re.search(r"20\d{2}", title) or re.search(r"20\d{2}", snippet) or re.search(r"20\d{2}", published):
            score += 1.0

        if any(k in title for k in ("最新", "new", "today", "本周", "今日")):
            score += 1.0

    return score


def _video_subject_boost(item: dict, query: str, source: str) -> float:
    """Boost items that contain the creator subject in title/channel text.

    This does not rewrite the user query; it only ranks provider results.
    """
    if source not in ("youtube", "bilibili"):
        return 0.0
    q = str(query or "")
    if not _is_video_intent_query(q):
        return 0.0
    subject = _extract_video_subject(q).strip().lower()
    if not subject:
        return 0.0
    title = str(item.get("title") or "").lower()
    snippet = str(item.get("snippet") or "").lower()
    if subject in title:
        return 5.0
    if subject in snippet:
        return 3.0
    return 0.0


def _postprocess_items(items: list[dict], query: str, source: str, sort: str, max_results: int) -> list[dict]:
    # Provider/domain filter
    src = str(source or "").lower()
    filtered = []
    for it in items:
        domain = str(it.get("domain") or "").lower()
        if src == "youtube" and domain and not ("youtube.com" in domain or "youtu.be" in domain):
            continue
        if src == "bilibili" and domain and "bilibili.com" not in domain:
            continue
        filtered.append(it)
    if filtered:
        items = filtered

    # Deduplicate by URL
    seen = set()
    dedup = []
    for it in items:
        u = str(it.get("url") or "").strip()
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        dedup.append(it)
    items = dedup

    # Rank
    toks = _tokenize_query(query)
    items.sort(
        key=lambda x: _score_item(x, toks, src, str(sort or "relevance")) + _video_subject_boost(x, query, src),
        reverse=True,
    )

    # Normalize ids after sorting
    out = []
    for idx, it in enumerate(items[: max(1, int(max_results or 5))], start=1):
        row = dict(it)
        row["id"] = str(idx)
        out.append(row)
    return out


def _search_provider_web(query: str, sort: str, max_results: int) -> str:
    _ = sort
    return tavily_search(query=query, max_results=max_results)


def _youtube_html_search(query: str, max_results: int) -> str:
    """Search directly on YouTube results page and parse top videos.

    This avoids generic web engine drift for creator-name queries.
    """
    q = str(query or "").strip()
    if not q:
        return json.dumps({"results": []}, ensure_ascii=False)
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as response:
            html_text = response.read().decode("utf-8", errors="ignore")

        pat = re.compile(
            r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"\}\].*?'
            r'"ownerText":\{"runs":\[\{"text":"(.*?)","navigationEndpoint"',
            re.DOTALL,
        )

        results = []
        seen = set()
        for vid, raw_title, raw_owner in pat.findall(html_text):
            if vid in seen:
                continue
            seen.add(vid)
            title = html.unescape(str(raw_title or "")).strip()
            owner = html.unescape(str(raw_owner or "")).strip()
            if not title:
                continue
            results.append(
                {
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "snippet": owner,
                }
            )
            if len(results) >= max_results:
                break

        return json.dumps({"results": results}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "NetworkError", "message": str(e)}, ensure_ascii=False)


def _search_provider_youtube(query: str, sort: str, max_results: int) -> str:
    q = str(query or "").strip()
    # First try native YouTube search to reduce topic-drift.
    native = _youtube_html_search(query=q, max_results=max_results)
    try:
        payload = json.loads(native)
        if isinstance(payload, dict) and isinstance(payload.get("results"), list) and payload.get("results"):
            return native
    except Exception:
        pass

    qq = f"site:youtube.com {q}"
    if str(sort or "").strip().lower() == "latest":
        qq = f"最新 {qq}"
    return tavily_search(query=qq, max_results=max_results)


def _search_provider_bilibili(query: str, sort: str, max_results: int) -> str:
    q = str(query or "").strip()
    qq = f"site:bilibili.com {q}"
    if str(sort or "").strip().lower() == "latest":
        qq = f"最新 {qq}"
    return tavily_search(query=qq, max_results=max_results)


def search(
    query: str,
    source: str = "auto",
    sort: str = "relevance",
    max_results: int = 5,
    filters: dict | None = None,
) -> str:
    """Unified search primitive.

    Args:
      query: user query
      source: auto|web|youtube|bilibili
      sort: relevance|latest
      max_results: number of results
      filters: provider-specific optional filters (reserved)
    """
    q = str(query or "").strip()
    if not q:
        return json.dumps(
            {
                "success": False,
                "error": "InvalidInput",
                "message": "query 为空",
                "source_requested": source,
                "source_used": "none",
                "items": [],
                "results": [],
            },
            ensure_ascii=False,
        )

    src_req = str(source or "auto").strip().lower() or "auto"
    src = src_req if src_req in ("web", "youtube", "bilibili") else "auto"
    max_n = max(1, min(10, int(max_results or 5)))
    _filters = filters if isinstance(filters, dict) else {}

    q_norm = q

    providers_map = {
        "web": _search_provider_web,
        "youtube": _search_provider_youtube,
        "bilibili": _search_provider_bilibili,
    }

    providers = [src] if src != "auto" else ["web", "youtube", "bilibili"]
    last_error: dict | None = None

    for used in providers:
        provider_fn = providers_map.get(used)
        if provider_fn is None:
            continue
        q_variants = [q_norm]
        if used in ("youtube", "bilibili"):
            q_variants = _video_query_variants(q_norm)

        for q_try in q_variants:
            raw_text = provider_fn(q_try, str(sort or "relevance"), max_n)
            try:
                raw_payload = json.loads(raw_text)
            except Exception:
                raw_payload = {"error": "InvalidResponse", "message": "search response is not json"}

            # Provider-level error; try next variant/provider.
            if isinstance(raw_payload, dict) and raw_payload.get("error"):
                last_error = dict(raw_payload)
                continue

            items = _normalize_search_items(raw_payload, source=used, provider="tavily")
            items = _postprocess_items(items, query=q_try, source=used, sort=str(sort or "relevance"), max_results=max_n)
            if items:
                return json.dumps(
                    {
                        "success": True,
                        "query": q,
                        "source_requested": src_req,
                        "source_used": used,
                        "sort": str(sort or "relevance"),
                        "filters": _filters,
                        "items": items,
                        # Backward compatibility for old callers.
                        "results": items,
                    },
                    ensure_ascii=False,
                )

        last_error = {"error": "NotFound", "message": "没有搜索结果"}
        if src != "auto":
            break

    err = last_error or {"error": "NotFound", "message": "没有搜索结果"}
    return json.dumps(
        {
            "success": False,
            "error": str(err.get("error") or "SearchError"),
            "message": str(err.get("message") or "search failed"),
            "source_requested": src_req,
            "source_used": "none",
            "query": q,
            "items": [],
            "results": [],
        },
        ensure_ascii=False,
    )


def search_and_open(query: str, prefer_domains: list[str] | None = None, max_results: int = 5) -> str:
    """Search and open the best result."""
    q = str(query or "").strip()
    if not q:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "query 为空"}, ensure_ascii=False)

    try:
        payload = json.loads(tavily_search(q, max_results=max(1, min(10, int(max_results or 5)))))
        items = payload.get("results") if isinstance(payload, dict) else None
    except Exception:
        items = None
    if not isinstance(items, list) or not items:
        return json.dumps({"success": False, "error": "NotFound", "message": "没有搜索结果"}, ensure_ascii=False)

    prefer = [str(d).strip().lower() for d in (prefer_domains or []) if str(d).strip()]

    def domain_of(url: str) -> str:
        try:
            return urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return ""

    chosen = items[0]
    if prefer:
        for it in items:
            url = str((it or {}).get("url") or "")
            if any(p in domain_of(url) for p in prefer):
                chosen = it
                break

    url = str((chosen or {}).get("url") or "").strip()
    title = str((chosen or {}).get("title") or "").strip()
    if not url:
        return json.dumps({"success": False, "error": "NotFound", "message": "结果缺少 url"}, ensure_ascii=False)
    _ = open_url(url)
    return json.dumps({"success": True, "title": title, "url": url}, ensure_ascii=False)


def take_screenshot() -> str:
    """Take a screenshot to Desktop."""
    try:
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        os.makedirs(desktop, exist_ok=True)
        ts = int(time.time())
        path = os.path.join(desktop, f"kage_screenshot_{ts}.png")
        proc = subprocess.run(["screencapture", "-x", path], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            return json.dumps({"success": False, "error": "ExecutionError", "message": msg or "screencapture failed"}, ensure_ascii=False)
        return json.dumps({"success": True, "path": path}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)


def skills_save_local(
    name: str,
    description: str,
    body: str = "",
    target_dir: str = "~/.kage/skills",
    overwrite: bool = False,
) -> str:
    """Save a local markdown skill as `SKILL.md`.

    The skill will be created at:
      <target_dir>/<name>/SKILL.md
    """
    raw_name = str(name or "").strip().lower()
    desc = str(description or "").strip()
    if not raw_name:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "name 为空"}, ensure_ascii=False)
    if not desc:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "description 为空"}, ensure_ascii=False)

    # slugify
    safe = re.sub(r"[^a-z0-9\-]+", "-", raw_name).strip("-")
    safe = re.sub(r"-+", "-", safe) or "skill"

    base = os.path.expanduser(str(target_dir or "~/.kage/skills"))
    skill_dir = os.path.join(base, safe)
    path = os.path.join(skill_dir, "SKILL.md")

    try:
        os.makedirs(skill_dir, exist_ok=True)
    except Exception as exc:
        return json.dumps({"success": False, "error": "WriteError", "message": str(exc)}, ensure_ascii=False)

    if os.path.exists(path) and not bool(overwrite):
        return json.dumps({"success": True, "created": False, "path": path, "name": safe}, ensure_ascii=False)

    md = "\n".join(
        [
            "---",
            f"name: {safe}",
            f"description: {desc}",
            "---",
            "",
            f"# {safe}",
            "",
            (str(body or "").rstrip() + "\n") if body else "",
        ]
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
    except Exception as exc:
        return json.dumps({"success": False, "error": "WriteError", "message": str(exc)}, ensure_ascii=False)

    return json.dumps({"success": True, "created": True, "path": path, "name": safe}, ensure_ascii=False)


# ============== macOS Shortcuts ==============


def shortcuts_list() -> str:
    """List available Apple Shortcuts (macOS).

    Returns JSON: {success, shortcuts: [name...]}
    """
    try:
        proc = subprocess.run(
            ["shortcuts", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return json.dumps({"success": False, "error": "MissingDependency", "message": "shortcuts 命令不可用"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return json.dumps({"success": False, "error": "ExecutionError", "message": msg}, ensure_ascii=False)

    names = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    return json.dumps({"success": True, "shortcuts": names}, ensure_ascii=False)


def shortcuts_run(name: str, input_text: str = "") -> str:
    """Run an Apple Shortcut by name.

    Returns JSON: {success, output}
    """
    n = str(name or "").strip()
    if not n:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "name 为空"}, ensure_ascii=False)

    cmd = ["shortcuts", "run", n]
    it = str(input_text or "")
    if it:
        cmd.extend(["--input", it])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return json.dumps({"success": False, "error": "MissingDependency", "message": "shortcuts 命令不可用"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return json.dumps({"success": False, "error": "ExecutionError", "message": err or out or "failed"}, ensure_ascii=False)
    return json.dumps({"success": True, "output": out}, ensure_ascii=False)


def shortcuts_create(name: str) -> str:
    """Create an empty shortcut with a given name (macOS Shortcuts).

    Note: AppleScript can create the shortcut object, but cannot reliably
    populate actions across OS versions. This is still useful as a scaffold.
    """
    n = str(name or "").strip()
    if not n:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "name 为空"}, ensure_ascii=False)
    # Create via AppleScript
    script = f'tell application "Shortcuts" to make new shortcut with properties {{name:"{n}"}}'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return json.dumps({"success": False, "error": "ExecutionError", "message": msg}, ensure_ascii=False)
    return json.dumps({"success": True, "name": n}, ensure_ascii=False)


def shortcuts_delete(name: str) -> str:
    """Delete a shortcut by name."""
    n = str(name or "").strip()
    if not n:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "name 为空"}, ensure_ascii=False)
    script = f'tell application "Shortcuts" to delete shortcut "{n}"'
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return json.dumps({"success": False, "error": "ExecutionError", "message": msg}, ensure_ascii=False)
    return json.dumps({"success": True, "name": n}, ensure_ascii=False)


def shortcuts_view(name: str) -> str:
    """Open a shortcut in the Shortcuts app UI."""
    n = str(name or "").strip()
    if not n:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "name 为空"}, ensure_ascii=False)
    try:
        proc = subprocess.run(["shortcuts", "view", n], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return json.dumps({"success": False, "error": "MissingDependency", "message": "shortcuts 命令不可用"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": "ExecutionError", "message": str(exc)}, ensure_ascii=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return json.dumps({"success": False, "error": "ExecutionError", "message": msg}, ensure_ascii=False)
    return json.dumps({"success": True, "name": n}, ensure_ascii=False)


def shortcuts_bootstrap_kage() -> str:
    """Ensure a basic set of kage_* shortcuts exist.

    Creates missing shortcuts as empty scaffolds and returns which were created.
    """
    base = [
        "kage_wifi_on",
        "kage_wifi_off",
        "kage_bluetooth_on",
        "kage_bluetooth_off",
    ]
    existing = []
    created = []
    try:
        listed = json.loads(shortcuts_list())
        names = set(listed.get("shortcuts") or []) if listed.get("success") else set()
    except Exception:
        names = set()

    for n in base:
        if n in names:
            existing.append(n)
            continue
        out = json.loads(shortcuts_create(n))
        if out.get("success"):
            created.append(n)
    return json.dumps({"success": True, "existing": existing, "created": created}, ensure_ascii=False)

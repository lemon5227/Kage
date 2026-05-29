"""Web and search tools — tavily, web_fetch, smart_search, search."""

import datetime
import json
import subprocess
import urllib.request
import urllib.parse
import urllib.error as urllib_error
import os
import re
import logging
import time

from core.tools.html_ops import strip_html_tags, truncate_output
from core.tools._response import ok, err

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Maximum bytes to read from a web response before truncation (1 MB)
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024

# Blocked shell patterns for exec_command safety
_BLOCKED_COMMAND_PATTERNS = re.compile(
    r"(rm\s+-rf\s+/|mkfs|dd\s+if=|:(){ :|curl.*\|\s*sh|wget.*\|\s*sh|"
    r"chmod\s+-R\s+777\s+/|shutdown|reboot|halt|init\s+[06])",
    re.IGNORECASE,
)

# Pre-compiled regexes for hot-path tokenization and parsers
_QUERY_TOKEN_RE = re.compile(r'[\u4e00-\u9fff]+|[a-zA-Z]+|\d+')
_DUCKDUCKGO_RE = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
_DUCKDUCKGO_TAG_RE = re.compile(r'<[^>]+>')
_YOUTUBE_VIDEO_RE = re.compile(r'"videoId":"([^"]+)".*?"title":"([^"]+)"', re.DOTALL)
_BILIBILI_RE = re.compile(r'data-title="([^"]*)".*?href="(//[^"]*)"')


def _tavily_api_search(query: str, max_results: int, api_key: str) -> str:
    """Tavily API search."""
    try:
        url = "https://api.tavily.com/search"
        data = json.dumps({"api_key": api_key, "query": query, "max_results": max_results, "include_answer": False}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
        results = [{"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")[:200]} for item in result.get("results", [])[:max_results]]
        return json.dumps({"success": True, "results": results}, ensure_ascii=False)
    except urllib_error.URLError as e:
        if hasattr(e, 'reason') and 'timed out' in str(e.reason).lower():
            return err("Timeout", "搜索超时")
        return err("NetworkError", str(e))
    except Exception as e:
        return err("NetworkError", str(e))


def _duckduckgo_fallback(query: str, max_results: int) -> str:
    """DuckDuckGo HTML search fallback."""
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as response:
            html_text = response.read().decode('utf-8', errors='replace')
        results = parse_duckduckgo_html(html_text, max_results)
        return json.dumps({"success": True, "results": [{"title": t, "url": u, "snippet": ""} for t, u in results]}, ensure_ascii=False)
    except Exception as e:
        return err("SearchFailed", str(e))


def parse_duckduckgo_html(html_text: str, max_results: int = 5) -> list[tuple[str, str]]:
    """Parse DuckDuckGo HTML search results."""
    results = []
    for match in _DUCKDUCKGO_RE.finditer(html_text):
        if len(results) >= max_results:
            break
        url = match.group(1)
        title = _DUCKDUCKGO_TAG_RE.sub('', match.group(2)).strip()
        if url and title:
            results.append((title, url))
    return results


def tavily_search(query: str, max_results: int = 5) -> str:
    """Search using Tavily API, fallback to DuckDuckGo."""
    api_key = ""
    try:
        from core.config_loader import get_config
        api_key = get_config("tavily_api_key", "")
    except Exception:
        pass
    if api_key:
        return _tavily_api_search(query, max_results, api_key)
    return _duckduckgo_fallback(query, max_results)


def web_fetch(url: str) -> str:
    """Fetch web page content and extract text."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get('Content-Type', '')
            # Check Content-Length to avoid downloading huge files
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > _MAX_RESPONSE_BYTES:
                return err("TooLarge", f"响应过大 ({int(content_length)} bytes)")
            # Read in chunks with size limit
            chunks = []
            total = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                chunks.append(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    break
            raw = b"".join(chunks).decode('utf-8', errors='replace')
        if 'text/html' in content_type:
            text = strip_html_tags(raw)
        else:
            text = raw
        return truncate_output(text)
    except urllib_error.URLError as e:
        if hasattr(e, 'reason') and 'timed out' in str(e.reason).lower():
            return err("Timeout", "网页抓取超时")
        return err("NetworkError", str(e))
    except Exception as e:
        return err("FetchFailed", str(e))


def exec_command(command: str, timeout: int = 30) -> str:
    """Execute a shell command with safety checks."""
    command = str(command or "").strip()
    if not command:
        return err("InvalidInput", "命令不能为空")
    # Block dangerous patterns
    if _BLOCKED_COMMAND_PATTERNS.search(command):
        return err("Blocked", "命令包含危险操作，已拒绝执行")
    try:
        # Use shell=True but with explicit /bin/sh for predictability.
        # We keep shell=True because commands may use pipes, redirects, etc.
        # Safety is enforced by the blocklist above + tool_executor's own checks.
        result = subprocess.run(
            ["/bin/sh", "-c", command],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not output.strip() and result.returncode == 0:
            return ok(message="命令执行成功，无输出")
        return json.dumps(
            {"success": result.returncode == 0, "output": truncate_output(output), "returncode": result.returncode},
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired:
        return err("Timeout", f"命令执行超时 ({timeout}s)")
    except Exception as e:
        return err("ExecutionFailed", str(e))


def open_url(url: str) -> str:
    """Open URL in default browser."""
    try:
        subprocess.run(["open", url], check=False)
        return ok(opened=url)
    except Exception as e:
        return err("OpenFailed", str(e))


def open_app(app_name: str) -> str:
    """Open an application by name."""
    try:
        subprocess.run(["open", "-a", app_name], check=False)
        return ok(opened=app_name)
    except Exception as e:
        return err("OpenFailed", str(e))


def open_website(site: str) -> str:
    """Open a website by name or URL."""
    site_map = {"b站": "https://bilibili.com", "哔哩哔哩": "https://bilibili.com", "知乎": "https://zhihu.com", "百度": "https://baidu.com"}
    url = site_map.get(site, site)
    if not url.startswith("http"):
        url = f"https://{url}"
    return open_url(url)


def take_screenshot() -> str:
    """Take a screenshot (macOS)."""
    try:
        screenshots_dir = os.path.expanduser("~/Desktop/Screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        filename = f"screenshot_{int(time.time())}.png"
        filepath = os.path.join(screenshots_dir, filename)
        subprocess.run(["screencapture", "-x", filepath], check=True)
        return ok(path=filepath)
    except Exception as e:
        return err("ScreenshotFailed", str(e))


def get_time() -> str:
    """Get current time."""
    now = datetime.datetime.now()
    return ok(time=now.strftime("%Y-%m-%d %H:%M:%S"), weekday=now.strftime("%A"))


def system_control(target: str, action: str, value: str = "") -> str:
    """Delegate to system_control module."""
    from core.system_control import system_control as _sc
    return _sc(target, action, value)


def system_capabilities() -> str:
    """Return system capabilities."""
    from core.system_control import system_capabilities as _cap
    return _cap()


def smart_search(query: str, max_results: int = 5, strategy: str = "auto") -> str:
    """Smart search: auto-select best provider based on query intent."""
    return search(query, max_results=max_results, strategy=strategy)


def _normalize_search_items(raw_payload: dict, source: str, provider: str) -> list[dict]:
    """Normalize search results from different providers."""
    items = raw_payload.get("results", raw_payload.get("items", []))
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "snippet": str(item.get("snippet", item.get("content", "")))[:300],
            "source": source,
            "provider": provider,
        })
    return normalized


def _tokenize_query(q: str) -> list[str]:
    """Tokenize search query."""
    return _QUERY_TOKEN_RE.findall(q.lower())


def _is_video_intent_query(q: str) -> bool:
    """Check if query is video-related."""
    video_keywords = ["视频", "观看", "教程", "演示", "b站", "bilibili", "youtube", "yt", "播放", "clip"]
    return any(kw in q.lower() for kw in video_keywords)


def _extract_video_subject(query: str) -> str:
    """Extract video subject from query."""
    q = query.lower()
    for prefix in ["看", "观看", "找", "搜索", "播放"]:
        if q.startswith(prefix):
            q = q[len(prefix):]
    for suffix in ["的视频", "视频", "教程", "演示"]:
        if q.endswith(suffix):
            q = q[:-len(suffix)]
    return q.strip()


def _video_query_variants(query: str) -> list[str]:
    """Generate search query variants for video content."""
    subject = _extract_video_subject(query)
    variants = [query, subject]
    if subject:
        variants.extend([f"{subject} bilibili", f"{subject} youtube", f"{subject} 视频"])
    return list(dict.fromkeys(v for v in variants if v))


def _score_item(item: dict, tokens: list[str], source: str, sort: str) -> float:
    """Score search item by relevance."""
    score = 0.0
    title = item.get("title", "").lower()
    snippet = item.get("snippet", "").lower()
    for token in tokens:
        if token in title:
            score += 3.0
        if token in snippet:
            score += 1.0
    if sort == "relevance":
        score *= 1.0
    elif sort == "date":
        score *= 0.8
    return score


def _video_subject_boost(item: dict, query: str, source: str) -> float:
    """Boost score for video-related items."""
    subject = _extract_video_subject(query)
    if not subject:
        return 0.0
    title = item.get("title", "").lower()
    if subject in title:
        return 2.0
    return 0.0


def _postprocess_items(items: list[dict], query: str, source: str, sort: str, max_results: int) -> list[dict]:
    """Post-process and rank search items."""
    tokens = _tokenize_query(query)
    scored = []
    for item in items:
        score = _score_item(item, tokens, source, sort)
        if _is_video_intent_query(query):
            score += _video_subject_boost(item, query, source)
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def _youtube_html_search_raw(query: str, max_results: int) -> list[dict]:
    """Search YouTube via HTML scraping. Returns list of dicts (no JSON)."""
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html_text = resp.read().decode('utf-8', errors='replace')
        results = []
        for match in _YOUTUBE_VIDEO_RE.finditer(html_text):
            if len(results) >= max_results:
                break
            vid = match.group(1)
            title = match.group(2).replace('\\u0026', '&')
            results.append({"title": title, "url": f"https://youtube.com/watch?v={vid}", "source": "youtube"})
        return results
    except Exception:
        return []


def _youtube_html_search(query: str, max_results: int) -> str:
    """Search YouTube via HTML scraping. Returns JSON string (compat wrapper)."""
    try:
        return json.dumps({"success": True, "results": _youtube_html_search_raw(query, max_results)}, ensure_ascii=False)
    except Exception as e:
        return err("SearchFailed", str(e))


def _search_provider_youtube(query: str, sort: str, max_results: int) -> str:
    """Search YouTube."""
    return _youtube_html_search(query, max_results)


def _search_provider_bilibili_raw(query: str, max_results: int) -> list[dict]:
    """Search Bilibili. Returns list of dicts (no JSON)."""
    try:
        url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html_text = resp.read().decode('utf-8', errors='replace')
        results = []
        for match in _BILIBILI_RE.finditer(html_text):
            if len(results) >= max_results:
                break
            title = match.group(1)
            url_path = match.group(2)
            if title and url_path:
                results.append({"title": title, "url": f"https:{url_path}", "source": "bilibili"})
        return results
    except Exception:
        return []


def _search_provider_bilibili(query: str, sort: str, max_results: int) -> str:
    """Search Bilibili. Returns JSON string (compat wrapper)."""
    try:
        return json.dumps({"success": True, "results": _search_provider_bilibili_raw(query, max_results)}, ensure_ascii=False)
    except Exception as e:
        return err("SearchFailed", str(e))


def search(query: str, max_results: int = 5, strategy: str = "auto", sort: str = "relevance") -> str:
    """Unified search across multiple providers."""
    q = str(query or "").strip()
    if not q:
        return err("InvalidInput", "query 不能为空")

    if strategy == "youtube":
        return _search_provider_youtube(q, sort, max_results)
    if strategy == "bilibili":
        return _search_provider_bilibili(q, sort, max_results)

    # Auto strategy: detect video intent
    if _is_video_intent_query(q):
        variants = _video_query_variants(q)
        all_items: list[dict] = []
        for variant in variants[:3]:
            # Use raw helpers to avoid 4 redundant json.dumps + json.loads per variant.
            try:
                all_items.extend(_youtube_html_search_raw(variant, max_results))
            except Exception:
                pass
            try:
                all_items.extend(_search_provider_bilibili_raw(variant, max_results))
            except Exception:
                pass
        items = _postprocess_items(all_items, q, "video", sort, max_results)
        return json.dumps({"success": True, "results": items, "strategy": "video_auto"}, ensure_ascii=False)

    # Default: web search
    return tavily_search(q, max_results)


def search_and_open(query: str, prefer_domains: list[str] | None = None, max_results: int = 5) -> str:
    """Search and open the best matching result."""
    result = search(query, max_results=max_results)
    try:
        data = json.loads(result)
        items = data.get("results", [])
        if not items:
            return err("NoResults", "未找到结果")
        # Prefer specific domains
        if prefer_domains:
            for item in items:
                url = item.get("url", "").lower()
                if any(d in url for d in prefer_domains):
                    return open_url(item["url"])
        return open_url(items[0]["url"])
    except Exception as e:
        return err("OpenFailed", str(e))

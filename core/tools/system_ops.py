"""System operation tools — control, time, screenshots, commands."""

import json
import subprocess
import time
import os


def exec_command(command: str, timeout: int = 30) -> str:
    """Execute a shell command."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        output = (result.stdout or "") + (result.stderr or "")
        if not output.strip() and result.returncode == 0:
            return json.dumps({"success": True, "message": "命令执行成功，无输出"}, ensure_ascii=False)
        return json.dumps({"success": result.returncode == 0, "output": output[:5000], "returncode": result.returncode}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Timeout", "message": f"命令执行超时 ({timeout}s)"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "ExecutionFailed", "message": str(e)}, ensure_ascii=False)


def open_url(url: str) -> str:
    """Open URL in default browser."""
    try:
        subprocess.run(["open", url], check=False)
        return json.dumps({"success": True, "opened": url}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "OpenFailed", "message": str(e)}, ensure_ascii=False)


def open_app(app_name: str) -> str:
    """Open an application by name."""
    try:
        subprocess.run(["open", "-a", app_name], check=False)
        return json.dumps({"success": True, "opened": app_name}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "OpenFailed", "message": str(e)}, ensure_ascii=False)


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
        return json.dumps({"success": True, "path": filepath}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "ScreenshotFailed", "message": str(e)}, ensure_ascii=False)


def get_time() -> str:
    """Get current time."""
    import datetime
    now = datetime.datetime.now()
    return json.dumps({"success": True, "time": now.strftime("%Y-%m-%d %H:%M:%S"), "weekday": now.strftime("%A")}, ensure_ascii=False)


def system_control(target: str, action: str, value: str = "") -> str:
    """Delegate to system_control module."""
    from core.system_control import system_control as _sc
    return _sc(target, action, value)


def system_capabilities() -> str:
    """Return system capabilities."""
    from core.system_control import system_capabilities as _cap
    return _cap()

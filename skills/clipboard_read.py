# 读取剪贴板内容
import subprocess

TRIGGERS = ["剪贴板", "复制的内容", "读剪贴板", "粘贴板"]

SKILL_INFO = {
    "name": "clipboard_read",
    "description": "读取剪贴板并返回前 200 字",
    "triggers": TRIGGERS,
    "action": "clipboard_read",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}

def execute(params: str) -> str:
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
    except Exception as e:
        return f"读取剪贴板失败: {e}"

    content = result.stdout.strip()
    if not content:
        return "剪贴板为空"
    preview = content[:200]
    return f"剪贴板内容: {preview}"

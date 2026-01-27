# 打开备忘录
import subprocess
import platform

TRIGGERS = ["打开备忘录", "打开便签", "打开笔记"]

SKILL_INFO = {
    "name": "open_notes",
    "description": "打开系统备忘录",
    "triggers": TRIGGERS,
    "action": "open_notes",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}


def execute(params: str) -> str:
    if platform.system() != "Darwin":
        return "当前系统暂不支持打开备忘录"
    try:
        subprocess.run(["open", "-a", "Notes"], check=True)
        return "已打开备忘录"
    except Exception as e:
        return f"打开失败: {e}"

# 打开最近修改的文件
import os
import subprocess

TRIGGERS = ["打开最近", "打开最新文件", "打开最近修改"]

SKILL_INFO = {
    "name": "open_recent",
    "description": "打开项目内最近修改的文件",
    "triggers": TRIGGERS,
    "action": "open_recent",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}

def execute(params: str) -> str:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    latest_file = None
    latest_time = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                mtime = os.path.getmtime(filepath)
                if mtime > latest_time:
                    latest_time = mtime
                    latest_file = filepath
            except Exception:
                continue

    if not latest_file:
        return "没有找到可打开的文件"

    try:
        subprocess.run(["open", latest_file], check=True)
        rel_path = os.path.relpath(latest_file, root_dir)
        return f"已打开 {rel_path}"
    except Exception as e:
        return f"打开失败: {e}"

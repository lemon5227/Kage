# 项目内搜索
import os

TRIGGERS = ["搜索代码", "查代码", "搜一下", "项目搜索", "代码里找"]

SKILL_INFO = {
    "name": "search_in_repo",
    "description": "在项目中搜索关键词",
    "triggers": TRIGGERS,
    "action": "search_in_repo",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要搜索的关键词"}
        },
        "required": ["query"]
    }
}

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}

def _extract_query(text: str) -> str:
    if not text:
        return ""
    for trigger in TRIGGERS:
        text = text.replace(trigger, "")
    return text.strip(" :：\n\t")

def execute(params: str) -> str:
    query = _extract_query(params or "")
    if not query:
        return "没有检测到搜索关键词"

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if len(matches) >= 10:
                break
            filepath = os.path.join(dirpath, filename)
            try:
                if os.path.getsize(filepath) > 1024 * 1024:
                    continue
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for idx, line in enumerate(f, 1):
                        if query in line:
                            rel_path = os.path.relpath(filepath, root_dir)
                            matches.append(f"{rel_path}:{idx} {line.strip()}")
                            if len(matches) >= 10:
                                break
            except Exception:
                continue

    if not matches:
        return "没有找到匹配结果"
    return "\n".join(matches)

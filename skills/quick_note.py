# 快速记笔记
import os
import datetime

TRIGGERS = ["记一下", "记笔记", "写笔记", "记录一下", "帮我记"]

SKILL_INFO = {
    "name": "quick_note",
    "description": "快速记录一条笔记到 ~/Documents/kage_notes.md",
    "triggers": TRIGGERS,
    "action": "quick_note",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "需要记录的内容"}
        },
        "required": ["text"]
    }
}

def execute(params: str) -> str:
    text = (params or "").strip()
    for trigger in TRIGGERS:
        text = text.replace(trigger, "")
    text = text.strip(" :：。\n\t")

    if not text:
        return "没有检测到要记录的内容"

    note_path = os.path.expanduser("~/Documents/kage_notes.md")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"- [{timestamp}] {text}\n"

    with open(note_path, "a", encoding="utf-8") as f:
        f.write(line)

    return "已记录到笔记"

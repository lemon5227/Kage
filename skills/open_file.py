# 打开文件技能 - 解决"打开刚才那个截图"的问题
import os
import subprocess
import glob

SKILL_INFO = {
    "name": "open_file",
    "description": "打开文件或最近的截图",
    "triggers": ["打开文件", "打开截图", "打开图片", "那个截图", "刚才的截图"],
    "action": "open_file",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径或关键词(如最新截图)"}
        }
    }
}

def execute(params: str) -> str:
    """
    打开文件
    params: 文件路径或特殊关键词如 "最新截图"
    """
    desktop = os.path.expanduser("~/Desktop")
    
    params = params or ""
    # 特殊处理：最新截图
    if "截图" in params or "screenshot" in params.lower() or not params:
        # 查找桌面上最新的 Kage 截图
        pattern = os.path.join(desktop, "kage_screenshot_*.png")
        screenshots = glob.glob(pattern)
        
        if screenshots:
            # 按修改时间排序，取最新的
            latest = max(screenshots, key=os.path.getmtime)
            try:
                subprocess.run(["open", latest], check=True)
                return f"已打开最新截图 📸"
            except Exception as e:
                return f"打开失败: {e}"
        else:
            return "没有找到 Kage 截图哦~"
    
    # 普通文件路径
    if os.path.exists(params):
        try:
            subprocess.run(["open", params], check=True)
            return f"已打开 {os.path.basename(params)}"
        except Exception as e:
            return f"打开失败: {e}"
    
    return f"找不到文件: {params}"

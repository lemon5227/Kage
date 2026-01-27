# 系统运行时间
import platform
import subprocess

TRIGGERS = ["运行时间", "开机时间", "系统运行多久", "系统运行时间"]

SKILL_INFO = {
    "name": "system_uptime",
    "description": "查看系统运行时间",
    "triggers": TRIGGERS,
    "action": "system_uptime",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}


def execute(params: str) -> str:
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(["uptime"], capture_output=True, text=True, check=True)
            return result.stdout.strip() or "未获取到运行时间"
        if platform.system() == "Linux":
            result = subprocess.run(["uptime", "-p"], capture_output=True, text=True, check=True)
            return result.stdout.strip() or "未获取到运行时间"
        return "当前系统暂不支持运行时间查询"
    except Exception as e:
        return f"运行时间查询失败: {e}"

# 电池状态
import platform
import subprocess

TRIGGERS = ["电池", "电量", "电池状态", "剩余电量"]

SKILL_INFO = {
    "name": "battery_status",
    "description": "查看当前电池状态",
    "triggers": TRIGGERS,
    "action": "battery_status",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}


def execute(params: str) -> str:
    if platform.system() != "Darwin":
        return "当前系统暂不支持电池查询"
    try:
        result = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        return output or "未获取到电池信息"
    except Exception as e:
        return f"电池查询失败: {e}"

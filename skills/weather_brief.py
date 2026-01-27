# 天气查询
import subprocess
from urllib.parse import quote

TRIGGERS = ["天气", "查天气", "天气怎么样", "天气预报"]

SKILL_INFO = {
    "name": "weather_brief",
    "description": "查询城市天气简报",
    "triggers": TRIGGERS,
    "action": "weather_brief",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称"}
        }
    }
}


def execute(params: str) -> str:
    city = _extract_city(params or "")
    if not city:
        city = "Beijing"
    url = f"wttr.in/{quote(city)}?format=3"
    try:
        result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        return output or "未获取到天气信息"
    except Exception as e:
        return f"天气查询失败: {e}"


def _extract_city(text: str) -> str:
    for trigger in TRIGGERS:
        text = text.replace(trigger, "")
    text = text.replace("天气", "").replace("如何", "").replace("怎么样", "")
    return text.strip(" :：\n\t")

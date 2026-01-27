# 日期查询
import datetime

TRIGGERS = ["今天几号", "今天星期几", "日期", "星期几", "几号"]

SKILL_INFO = {
    "name": "today_date",
    "description": "查询今天日期和星期",
    "triggers": TRIGGERS,
    "action": "today_date",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}


def execute(params: str) -> str:
    now = datetime.datetime.now()
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_map[now.weekday()]
    return now.strftime(f"%Y-%m-%d {weekday}")

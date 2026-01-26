# 冷笑话技能
import random

TRIGGERS = ["讲笑话", "冷笑话", "来个笑话", "讲个笑话"]

SKILL_INFO = {
    "name": "joke",
    "description": "随机讲一个短冷笑话",
    "triggers": TRIGGERS,
    "action": "joke",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}

JOKES = [
    "冷笑话：我很冷，因为是终端哒😤",
    "冷笑话：程序员最怕的雨是404哒💖",
    "冷笑话：我不是沉默，是在加载哒✨",
    "冷笑话：键盘很冷，因为没空格哒😤",
    "冷笑话：我没感情，只会输出哒💖",
    "冷笑话：bug不见了，是去度假哒✨",
    "冷笑话：我在等回应，不是卡住哒😤",
    "冷笑话：风扇在转，是因为我很热哒💖",
    "冷笑话：代码很冷，因为没有注释哒✨",
    "冷笑话：网速很慢，因为在想你哒😤",
]


def execute(params: str) -> str:
    return random.choice(JOKES)

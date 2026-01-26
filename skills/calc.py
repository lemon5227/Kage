# 安全计算
import ast
import re

TRIGGERS = ["计算", "算一下", "算一算", "算下"]

SKILL_INFO = {
    "name": "calc",
    "description": "安全计算简单表达式",
    "triggers": TRIGGERS,
    "action": "calc",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        },
        "required": ["expression"]
    }
}

ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Num,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.FloorDiv,
)

def _extract_expression(text: str) -> str:
    if not text:
        return ""
    for trigger in TRIGGERS:
        text = text.replace(trigger, "")
    text = text.replace("等于", "").replace("是多少", "")
    expr = re.sub(r"[^0-9\.+\-*/()%\s]", "", text)
    return expr.strip()

def _safe_eval(expr: str):
    node = ast.parse(expr, mode="eval")
    for child in ast.walk(node):
        if not isinstance(child, ALLOWED_NODES):
            raise ValueError("非法表达式")
    return eval(compile(node, "<calc>", "eval"), {"__builtins__": {}})

def execute(params: str) -> str:
    expr = _extract_expression(params or "")
    if not expr:
        return "没有检测到表达式"
    try:
        result = _safe_eval(expr)
    except Exception as e:
        return f"计算失败: {e}"
    return f"结果: {result}"

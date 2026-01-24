# Kage Skills 系统

Skills 是可插拔的能力扩展模块。每个 skill 是一个独立的 Python 文件。

## 如何添加新 Skill

1. 在 `skills/` 目录下创建新的 `.py` 文件
2. 定义 `SKILL_INFO` 字典和执行函数
3. 重启 Kage 即可加载

## Skill 文件模板

```python
# skills/example_skill.py

SKILL_INFO = {
    "name": "example",           # Skill 名称
    "description": "示例技能",    # 描述
    "triggers": ["示例", "example"],  # 触发词
    "action": "example_action"   # 动作名称
}

def execute(params: str) -> str:
    """执行技能"""
    return f"示例技能执行成功: {params}"
```

## 内置 Skills

- `open_file.py` - 打开文件/图片
- (更多待添加...)

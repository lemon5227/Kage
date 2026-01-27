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
    "action": "example_action",   # 动作名称
    "parameters": {              # 参数定义
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "参数说明"}
        },
        "required": ["param"]
    }
}

def execute(params: str) -> str:
    """执行技能"""
    return f"示例技能执行成功: {params}"
```

## 内置 Skills

- `open_file.py` - 打开文件/图片
- `quick_note.py` - 快速记笔记
- `calc.py` - 安全计算表达式
- `search_in_repo.py` - 项目内搜索
- `open_recent.py` - 打开最近修改文件
- `clipboard_read.py` - 读取剪贴板
- `mcp_client.py` - MCP 工具调用
- `mcp_fs_list.py` - MCP 列目录
- `mcp_fs_read.py` - MCP 读文件
- `mcp_fs_write.py` - MCP 写文件
- `joke.py` - 冷笑话随机回复
- `battery_status.py` - 电池状态查询
- `system_uptime.py` - 系统运行时间
- `weather_brief.py` - 天气简报查询
- `today_date.py` - 日期/星期查询
- `open_notes.py` - 打开备忘录
- `open_browser.py` - 打开浏览器
- `brightness_control.py` - 亮度快速调节
- `find_skills.py` - Skills 检索提示
- `social_content.py` - 社媒内容辅助
- `pptx.py` - 演示文稿技能
- `docx.py` - 文档技能
- `xlsx.py` - 表格技能
- `pdf.py` - PDF 技能
- `playwright_skill.py` - 浏览器自动化

"""
端到端测试脚本 - 测试 Kage 完整流程

测试项 (使用新的统一入口 system_control):
1. 系统控制：音量、亮度
2. Shell 命令：天气、网页状态
3. 应用控制：打开/关闭
"""

import asyncio
import os
import sys
import time

from scripts.harness import ensure_repo_root_on_path, make_tool_executor


def main():
    ensure_repo_root_on_path()
    ex = make_tool_executor()

    print("\n" + "="*50)
    print("🚀 Kage 端到端工具测试 (ToolExecutor)")
    print("="*50)

    tests = [
        ("音量调大", "system_control", {"target": "volume", "action": "up"}),
        ("音量调小", "system_control", {"target": "volume", "action": "down"}),
        ("亮度调低", "system_control", {"target": "brightness", "action": "down"}),
        ("亮度调高", "system_control", {"target": "brightness", "action": "up"}),
        ("打开计算器", "system_control", {"target": "app", "action": "open", "value": "Calculator"}),
    ]

    for name, tool, args in tests:
        print(f"\n👉 {name}: {tool} {args}")
        start = time.time()
        res = asyncio.run(ex.execute(tool, args))
        elapsed = time.time() - start
        print(f"   success={res.success} elapsed={elapsed:.2f}s")
        print(f"   result={res.result}")


if __name__ == "__main__":
    main()

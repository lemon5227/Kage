"""
端到端测试脚本 - 测试 Kage 完整流程

测试项 (使用新的统一入口 system_control):
1. 系统控制：音量、亮度
2. Shell 命令：天气、网页状态
3. 应用控制：打开/关闭
"""

import sys
import os
import time

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from core.tools import KageTools
    
    print("\n" + "="*50)
    print("🚀 Kage 端到端测试 (使用统一入口)")
    print("="*50)
    
    # Initialize Tools
    tools = KageTools()
    print("✅ KageTools Initialized.\n")
    
    # Helper
    def run_test(name, cmd, explanation):
        print(f"👉 [{name}]")
        print(f"   ℹ️  {explanation}")
        print(f"   💻 {cmd}")
        
        start = time.time()
        result = tools.execute(cmd)
        elapsed = time.time() - start
        
        status = "✅ OK" if "❌" not in result else "❌ FAIL"
        print(f"   📄 {result}")
        print(f"   ⏱️ {elapsed:.2f}s | {status}\n")
        return "❌" not in result
    
    passed = 0
    total = 0
    
    # --- 测试用例 ---
    tests = [
        ("音量调大", 'system_control("volume", "up")', "统一入口: 音量控制"),
        ("音量调小", 'system_control("volume", "down")', "统一入口: 音量控制"),
        ("亮度调低", 'system_control("brightness", "down")', "统一入口: 亮度控制"),
        ("亮度调高", 'system_control("brightness", "up")', "统一入口: 亮度控制"),
        ("查询天气", 'run_cmd("curl -s \'wttr.in/Beijing?format=3\'")', "Shell 命令: 天气"),
        ("网页状态", 'run_cmd("curl -I -s https://www.google.com | head -n 1")', "Shell 命令: HTTP 状态"),
        ("打开计算器", 'system_control("app", "open", "Calculator")', "统一入口: 打开应用"),
        ("关闭计算器", 'system_control("app", "close", "Calculator")', "统一入口: 关闭应用"),
    ]
    
    for name, cmd, desc in tests:
        total += 1
        if run_test(name, cmd, desc):
            passed += 1
        time.sleep(0.5)
    
    # --- 结果统计 ---
    print("="*50)
    print(f"📊 测试结果: {passed}/{total} 通过")
    if passed == total:
        print("🎉 全部通过！Kage 统一入口工作正常！")
    else:
        print("⚠️ 有失败项，请检查。")
    print("="*50)

except Exception as e:
    print(f"\n❌ FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()

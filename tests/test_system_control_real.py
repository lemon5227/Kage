"""
真实集成测试 - 会实际改变系统设置！

测试项：
1. 音量调大 (会听到变化)
2. 音量调小 (恢复)
3. 亮度调低 (屏幕会变暗)
4. 亮度调高 (恢复)
5. 打开应用 (Safari 会打开)
6. 关闭应用 (Safari 会关闭)

注意：WiFi 测试跳过，因为会断网
"""

import sys
import os
import time

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.tools import KageTools

def main():
    print("\n" + "="*50)
    print("🔥 真实集成测试 - 系统设置会被改变！")
    print("="*50)
    
    tools = KageTools()
    
    tests = [
        ("volume", "up", None, "音量调大 - 你应该听到变化"),
        ("volume", "down", None, "音量调小 - 恢复"),
        ("brightness", "down", None, "亮度调低 - 屏幕会变暗"),
        ("brightness", "up", None, "亮度调高 - 恢复"),
        ("wifi", "off", None, "WiFi 关闭 - 网络会断"),
        ("wifi", "on", None, "WiFi 开启 - 网络恢复"),
        ("bluetooth", "off", None, "蓝牙关闭"),
        ("bluetooth", "on", None, "蓝牙开启"),
        ("app", "open", "Calculator", "打开计算器"),
    ]
    
    for target, action, value, desc in tests:
        print(f"\n⏳ 测试: {desc}")
        print(f"   调用: system_control('{target}', '{action}', {repr(value)})")
        
        result = tools.system_control(target, action, value)
        print(f"   结果: {result}")
        
        # 暂停让用户观察效果
        time.sleep(1.5)
    
    # 关闭计算器
    print(f"\n⏳ 测试: 关闭计算器")
    result = tools.system_control("app", "close", "Calculator")
    print(f"   结果: {result}")
    
    print("\n" + "="*50)
    print("✅ 真实测试完成！请确认上述操作是否生效。")
    print("="*50)

if __name__ == "__main__":
    main()

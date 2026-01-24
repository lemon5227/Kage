"""
Kage 综合能力测试 - 覆盖所有日常场景

测试所有已知能力并分析回复质量
"""

import subprocess
import sys

def run_kage_test():
    print("\n" + "="*70)
    print("🧪 Kage 综合能力测试 - 覆盖所有日常场景")
    print("="*70)
    
    # 综合测试场景（不包含断网操作避免影响测试）
    test_scenarios = [
        # 时间日期
        ("⏰ 时间查询", "几点了"),
        ("📅 日期查询", "今天几号"),
        
        # 系统控制
        ("🔊 音量调大", "大声点"),
        ("🔉 音量调小", "小声点"),
        ("🔇 静音", "静音"),
        ("🔆 亮度调高", "亮一点"),
        ("🌙 亮度调低", "暗一点"),
        
        # 应用管理
        ("🧮 打开计算器", "打开计算器"),
        ("📝 打开备忘录", "打开备忘录"),
        ("🎵 打开音乐", "打开音乐"),
        ("📧 打开邮件", "打开邮件"),
        ("❌ 关闭计算器", "关掉计算器"),
        
        # 信息查询
        ("🌐 查IP", "查我IP"),
        ("🌤️ 查天气", "深圳天气"),
        
        # 网页操作
        ("🔍 打开百度", "打开百度"),
        ("🌐 打开Chrome", "打开谷歌浏览器"),
        
        # 聊天
        ("💬 闲聊", "你好呀"),
        
        # 退出
        ("💤 退出", "再见"),
    ]
    
    print(f"\n📋 将测试 {len(test_scenarios)} 个场景:")
    for i, (name, _) in enumerate(test_scenarios, 1):
        print(f"   {i}. {name}")
    
    commands = [cmd for _, cmd in test_scenarios]
    input_text = "\n".join(commands)
    
    print("\n🚀 启动 Kage...\n")
    print("-"*70)
    
    try:
        kage_python = "/Users/wenbo/miniconda3/envs/kage/bin/python"
        process = subprocess.Popen(
            [kage_python, "main.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd="/Users/wenbo/Kage"
        )
        
        stdout, _ = process.communicate(input=input_text, timeout=360)
        
        print(stdout)
        print("-"*70)
        
        # 分析
        print("\n📊 测试结果分析:\n")
        
        # 核心功能检查
        checks = [
            ("get_time", "时间查询工具"),
            ("system_control", "系统控制入口"),
            ("volume", "音量控制"),
            ("brightness", "亮度控制"),
            ("open_app", "应用打开"),
            ("close", "应用关闭"),
            ("run_cmd", "Shell命令"),
            ("open_url", "网页打开"),
            ("晚安", "正常退出"),
        ]
        
        passed = 0
        for indicator, name in checks:
            if indicator.lower() in stdout.lower():
                passed += 1
                print(f"   ✅ {name}")
            else:
                print(f"   ❌ {name}")
        
        # 意图统计
        command_count = stdout.count("[意图判断]: COMMAND")
        chat_count = stdout.count("[意图判断]: CHAT")
        
        print(f"\n📈 意图统计: COMMAND={command_count}, CHAT={chat_count}")
        
        # 异常检测
        print("\n🔍 异常检测:")
        issues = []
        if "Instruction" in stdout and stdout.count("Instruction") > 3:
            issues.append("重复 Instruction 乱码")
        if "\\N\\c" in stdout:
            issues.append("\\N\\c 乱码")
        if stdout.count("️️️") > 2:
            issues.append("重复 emoji 乱码")
        
        if issues:
            for issue in issues:
                print(f"   ⚠️ {issue}")
        else:
            print("   ✅ 无明显异常")
        
        total = len(checks)
        print(f"\n{'='*70}")
        print(f"📈 总结: {passed}/{total} 核心功能通过 ({passed/total*100:.0f}%)")
        print("="*70)
        
        return passed >= total * 0.8
        
    except subprocess.TimeoutExpired:
        process.kill()
        print("❌ 测试超时")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

if __name__ == "__main__":
    success = run_kage_test()
    sys.exit(0 if success else 1)

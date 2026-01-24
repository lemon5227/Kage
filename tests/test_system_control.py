"""
单元测试: 统一系统控制入口 system_control

测试场景:
1. 音量调大/调小
2. 亮度调高/调低
3. WiFi 开/关
4. 蓝牙 开/关 (需要 blueutil)
5. 打开/关闭应用
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.tools import KageTools


class TestUnifiedSystemControl(unittest.TestCase):
    
    def setUp(self):
        print("\n--- Initializing KageTools ---")
        self.tools = KageTools()
    
    # =========================================
    # 测试音量控制
    # =========================================
    @patch('subprocess.run')
    def test_volume_up(self, mock_run):
        print("Test: system_control('volume', 'up')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("volume", "up")
        print(f"  Result: {result}")
        
        self.assertIn("音量已调大", result)
        mock_run.assert_called()
        # Verify osascript was called
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "osascript")
    
    @patch('subprocess.run')
    def test_volume_down(self, mock_run):
        print("Test: system_control('volume', 'down')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("volume", "down")
        print(f"  Result: {result}")
        
        self.assertIn("音量已调小", result)
    
    # =========================================
    # 测试亮度控制
    # =========================================
    @patch('subprocess.run')
    def test_brightness_up(self, mock_run):
        print("Test: system_control('brightness', 'up')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("brightness", "up")
        print(f"  Result: {result}")
        
        self.assertIn("亮度已调高", result)
        # Verify key code 144 was used
        args = mock_run.call_args[0][0]
        self.assertIn("key code 144", args[2])
    
    @patch('subprocess.run')
    def test_brightness_down(self, mock_run):
        print("Test: system_control('brightness', 'down')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("brightness", "down")
        print(f"  Result: {result}")
        
        self.assertIn("亮度已调低", result)
        args = mock_run.call_args[0][0]
        self.assertIn("key code 145", args[2])
    
    # =========================================
    # 测试 WiFi 控制
    # =========================================
    @patch('subprocess.run')
    def test_wifi_on(self, mock_run):
        print("Test: system_control('wifi', 'on')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("wifi", "on")
        print(f"  Result: {result}")
        
        self.assertIn("WiFi 已开启", result)
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "networksetup")
    
    @patch('subprocess.run')
    def test_wifi_off(self, mock_run):
        print("Test: system_control('wifi', 'off')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("wifi", "off")
        print(f"  Result: {result}")
        
        self.assertIn("WiFi 已关闭", result)
    
    # =========================================
    # 测试应用控制
    # =========================================
    @patch('subprocess.run')
    def test_app_open(self, mock_run):
        print("Test: system_control('app', 'open', 'Safari')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("app", "open", "Safari")
        print(f"  Result: {result}")
        
        self.assertIn("已打开", result)
    
    @patch('subprocess.run')
    def test_app_close(self, mock_run):
        print("Test: system_control('app', 'close', 'Safari')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("app", "close", "Safari")
        print(f"  Result: {result}")
        
        self.assertIn("已关闭", result)
    
    # =========================================
    # 测试不支持的目标
    # =========================================
    def test_unknown_target(self):
        print("Test: system_control('unknown', 'do')")
        result = self.tools.system_control("unknown", "do")
        print(f"  Result: {result}")
        
        self.assertIn("不支持的控制目标", result)
    
    # =========================================
    # 测试中文参数
    # =========================================
    @patch('subprocess.run')
    def test_chinese_params(self, mock_run):
        print("Test: system_control('音量', '大')")
        mock_run.return_value.returncode = 0
        
        result = self.tools.system_control("音量", "大")
        print(f"  Result: {result}")
        
        self.assertIn("音量已调大", result)


if __name__ == '__main__':
    print("\n" + "="*50)
    print("统一系统控制入口 - 单元测试")
    print("="*50)
    unittest.main(verbosity=2)

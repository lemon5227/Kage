class KageRouter:
    """
    快速意图分类器 - 使用规则匹配代替 LLM
    从 ~1400ms 优化到 <1ms
    """
    
    # 命令关键词（匹配到任一则为 COMMAND）
    COMMAND_KEYWORDS = [
        # 应用控制
        "打开", "关闭", "启动", "退出", "运行",
        # 系统控制
        "音量", "声音", "亮度", "静音", "大声", "小声", "调高", "调低", "调大", "调小",
        "wifi", "蓝牙", "bluetooth",
        # 媒体控制
        "播放", "暂停", "继续", "下一首", "上一首", "放音乐", "听歌", "停止",
        # 信息查询
        "天气", "时间", "几点", "日期", "几号", "星期", "ip",
        # 文件操作
        "截图", "截屏", "创建", "删除", "复制", "粘贴",
        # 系统操作
        "关机", "重启", "睡眠", "锁屏",
        # 计算
        "计算", "算一下", "等于多少",
        # 搜索
        "搜索", "查找", "查一下", "帮我查",
        # 英文命令
        "open", "close", "volume", "brightness", "play", "pause", "next", "previous",
        "screenshot", "search", "check", "get", "show",
    ]
    
    # 闲聊关键词（优先级低于命令）
    CHAT_KEYWORDS = [
        "你好", "您好", "早上好", "晚上好", "嗨", "hi", "hello",
        "谢谢", "感谢", "辛苦了", "不错", "很好", "棒",
        "你是谁", "你叫什么", "介绍一下", "怎么样",
        "讲个笑话", "无聊", "陪我聊", "聊天",
    ]
    
    def __init__(self, model=None, tokenizer=None):
        # 保留参数兼容性，但不再使用 LLM
        self.model = model
        self.tokenizer = tokenizer
        
    def classify(self, user_input: str) -> str:
        """
        快速分类用户输入为 'CHAT' 或 'COMMAND'
        使用规则匹配，延迟 <1ms
        """
        if not user_input:
            return "CHAT"
        
        text = user_input.lower()
        
        # 检查命令关键词
        for keyword in self.COMMAND_KEYWORDS:
            if keyword in text:
                return "COMMAND"
        
        # 默认聊天
        return "CHAT"

# test_memory.py
from core.memory import MemorySystem

def test():
    # 1. 初始化
    print("--- 1. 正在唤醒 Kage 的海马体 ---")
    brain = MemorySystem()
    
    # 2. 存入不同情绪的记忆
    print("\n--- 2. 注入测试记忆 ---")
    brain.add_memory("今天吃到了很好吃的草莓蛋糕", emotion="happy", importance=2)
    brain.add_memory("刚才写的代码报错了，好烦", emotion="angry", importance=1)
    brain.add_memory("把那个红色的文件夹删掉", type="instruction", emotion="neutral", importance=5)

    # 3. 测试普通回忆 (应该包含情绪标签)
    print("\n--- 3. 测试普通回忆 (Query: 吃) ---")
    mems = brain.recall("吃")
    for m in mems:
        print(f"想起: {m['content']} [心情: {m['emotion']}]")

    # 4. 测试情绪过滤 (只回忆生气的事)
    print("\n--- 4. 测试情绪过滤 (只看 angry) ---")
    angry_mems = brain.recall("代码", filters={"emotion": "angry"})
    for m in angry_mems:
        print(f"想起: {m['content']} [心情: {m['emotion']}]")

if __name__ == "__main__":
    test()
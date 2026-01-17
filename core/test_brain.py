from core.brain import kageBrain

def test_brain():
    print("--- Testing Kage Brain ---")
    
    # 1. Initialize brain
    brain = kageBrain()
    
    # 2. Test think with some dummy memories
    memories = [
        {"content": "Master 喜欢吃草莓蛋糕", "emotion": "happy"},
        {"content": "Master 今天很累", "emotion": "sad"}
    ]
    
    user_input = "嘿，Kage，你还记得我喜欢吃什么吗？"
    
    print(f"\nUser: {user_input}")
    response = brain.think(user_input, memories=memories, current_emotion="happy")
    print(f"\nKage: {response}")

if __name__ == "__main__":
    test_brain()

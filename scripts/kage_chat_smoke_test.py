import asyncio

from scripts.harness import make_agentic_loop


def quick_chat_response(user_input: str):
    text = (user_input or "").strip()
    if not text:
        return None
    if "你是谁" in text:
        return "我是Kage，终端精灵哒💖"
    if "你能做什么" in text:
        return "系统控制/计算/文件工具哒💖"
    if "冷笑话" in text or "笑话" in text:
        return "我可以讲，不过现在更希望你给我一个要做的事。"
    return None


def polish_chat_response(text: str):
    if not text:
        return text
    cleaned = " ".join(text.split())
    cleaned = cleaned.replace("Master心情:", "").replace("Master心情", "")
    cleaned = cleaned.replace("@@@", "")
    cleaned = _filter_chat_text(cleaned)
    cleaned = _collapse_repeats(cleaned).strip()
    if len(cleaned) > 30:
        cleaned = cleaned[:30]
    if not any(mark in cleaned for mark in ("✨", "😤", "💖")):
        cleaned += "💖"
    if not cleaned.endswith(("哒", "捏", "哇")):
        cleaned += "哒"
    return cleaned


def _filter_chat_text(text: str):
    if not text:
        return text
    allowed_emoji = {"✨", "😤", "💖"}
    allowed_punct = set("，。！？!?、,.~:：;；()（）[]【】")
    output = []
    for ch in text:
        code = ord(ch)
        if ch in allowed_emoji:
            output.append(ch)
            continue
        if ch in allowed_punct:
            output.append(ch)
            continue
        if ch.isalnum() or ch.isspace():
            output.append(ch)
            continue
        if 0x4E00 <= code <= 0x9FFF:
            output.append(ch)
            continue
    return "".join(output)


def _collapse_repeats(text: str):
    if not text:
        return text
    output = []
    last_char = None
    repeat_count = 0
    for ch in text:
        if ch == last_char:
            repeat_count += 1
        else:
            repeat_count = 0
        last_char = ch
        if repeat_count < 2:
            output.append(ch)
    return "".join(output)


def collect_stream(stream):
    text = ""
    for chunk in stream:
        piece = getattr(chunk, "text", str(chunk))
        text += piece
    return text.strip()


def run():
    loop = make_agentic_loop()
    prompts = [
        "你好，Kage",
        "你是谁？",
        "我今天有点累",
        "讲个冷笑话",
        "你能做什么？",
        "谢谢你",
        "我有点紧张",
        "晚安",
        "你喜欢什么？",
    ]

    for prompt in prompts:
        print("\n=== User ===")
        print(prompt)
        quick = quick_chat_response(prompt)
        if quick:
            response = quick
        else:
            res = asyncio.run(loop.run(prompt))
            response = polish_chat_response(res.final_text)
        print("=== Kage ===")
        print(response)


if __name__ == "__main__":
    run()

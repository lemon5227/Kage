import asyncio

from scripts.harness import make_agentic_loop


async def run_case(loop, user_input: str):
    print("\n=== User ===")
    print(user_input)
    res = await loop.run(user_input)
    if res.tool_calls_executed:
        print("=== Tools ===")
        for tc in res.tool_calls_executed:
            name = tc.get("name")
            ok = tc.get("success")
            print(f"- {name}: {'ok' if ok else 'err'}")
    print("=== Kage ===")
    print(res.final_text)


def run():
    loop = make_agentic_loop()

    cases = [
        "帮我记一下：今天开会",
        "计算 12*(3+4)",
        "列目录 /Users/wenbo/Kage",
        "读文件 /Users/wenbo/Kage/readme.md",
        "搜索代码 ToolExecutor",
        "帮我写社媒内容",
        "帮我找技能",
        "做一个PPT",
        "写文档",
        "做个表格",
        "处理PDF",
        "用playwright测试网页 https://example.com",
    ]

    for user_input in cases:
        asyncio.run(run_case(loop, user_input))


if __name__ == "__main__":
    run()

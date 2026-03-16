import asyncio
import json

from scripts.harness import make_tool_executor


def run():
    ex = make_tool_executor()
    print("skills_find_remote:")
    res = asyncio.run(ex.execute("skills_find_remote", {"query": "find-skills", "max_results": 3}))
    print(res.result)

    try:
        payload = json.loads(str(res.result))
        first = (payload.get("results") or [None])[0] or {}
        print("\nfirst candidate:")
        print(first)
    except Exception:
        pass


if __name__ == "__main__":
    run()

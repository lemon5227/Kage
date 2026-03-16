import os

from scripts.harness import make_tool_executor


def run():
    ex = make_tool_executor()
    test_path = os.path.join(os.getcwd(), "temp_fs_test.txt")

    import asyncio
    print("fs_write:")
    print(asyncio.run(ex.execute("fs_write", {"path": test_path, "content": "kage fs test"})).result)
    print("\nfs_undo_last:")
    print(asyncio.run(ex.execute("fs_undo_last", {})).result)


if __name__ == "__main__":
    run()

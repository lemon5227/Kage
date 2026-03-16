import os
import sys

import asyncio
import pytest


def pytest_configure():
    # Ensure repository root is on sys.path so `import core...` works.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Ensure a usable default event loop exists for each test.

    Some tests still call `asyncio.get_event_loop().run_until_complete(...)`.
    Additionally, `asyncio.run()` clears the current loop, so we must
    re-establish one on subsequent tests.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    yield

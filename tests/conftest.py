import os
import shlex
import subprocess
import sys

import asyncio
import pytest

# Binaries that change the user's desktop/GUI session state. Tests must never
# invoke these for real: `open` launches the default browser (pytest was opening
# YouTube/Bilibili), `open -a Shortcuts` launches the Shortcuts app, and
# `networksetup`/`pmset` change Wi-Fi, volume and display settings.
DESKTOP_SIDE_EFFECT_BINARIES = frozenset({
    "open",
    "osascript",
    "shortcuts",
    "screencapture",
    "networksetup",
    "pmset",
    "brightness",
    "displayplacer",
    "caffeinate",
})


class DesktopSideEffectError(AssertionError):
    """A test tried to perform a real desktop side effect."""


class _FakePopen:
    """Stand-in for subprocess.Popen that never launches anything."""

    returncode = 0
    pid = 0
    stdin = None
    stdout = None
    stderr = None

    def __init__(self, args=None, **kwargs):
        self.args = args

    def communicate(self, input=None, timeout=None):  # noqa: A002 - subprocess signature
        return ("", "")

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        return None

    def terminate(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _desktop_binary(args) -> str | None:
    if isinstance(args, bytes):
        args = args.decode("utf-8", errors="replace")
    if isinstance(args, str):
        argv = shlex.split(args)
    elif isinstance(args, (list, tuple)):
        argv = [str(item) for item in args]
    else:
        return None
    if not argv:
        return None
    name = os.path.basename(str(argv[0]).strip())
    return name if name in DESKTOP_SIDE_EFFECT_BINARIES else None


def _guard(call_name: str, original, attempts: list[str]):
    """Record desktop side-effect attempts and return a harmless result.

    Recording (instead of raising) matters: the tool functions wrap their calls in
    a broad ``except Exception``, which would swallow an exception and let the test
    pass silently. The fixture asserts on the recorded attempts at teardown, so a
    real launch can never go unnoticed.
    """

    def wrapper(*args, **kwargs):
        candidate = args[0] if args else kwargs.get("args")
        binary = _desktop_binary(candidate)
        if binary is not None:
            attempts.append(f"subprocess.{call_name}({candidate!r})")
            if call_name == "Popen":
                return _FakePopen(candidate)
            if call_name in ("check_output", "check_call"):
                return b"" if call_name == "check_output" else 0
            return subprocess.CompletedProcess(args=candidate, returncode=0,
                                               stdout="", stderr="")
        return original(*args, **kwargs)

    wrapper.__name__ = getattr(original, "__name__", call_name)
    return wrapper


def pytest_configure(config):
    # Ensure repository root is on sys.path so `import core...` works.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    config.addinivalue_line(
        "markers",
        "allow_desktop_side_effects: permit real GUI/session commands (manual tests only)",
    )


@pytest.fixture(autouse=True)
def _block_desktop_side_effects(request, monkeypatch):
    """Fail loudly instead of opening browsers/apps or changing system settings.

    Regression guard for a real incident: `test_open_website.py` patched the wrong
    module attribute, so running pytest opened YouTube/Bilibili in the user's
    browser; `shortcuts_create` launched the Shortcuts app; `open_app("")` ran
    `open -a ""`.
    """
    if request.node.get_closest_marker("allow_desktop_side_effects"):
        yield
        return

    attempts: list[str] = []
    for call_name in ("run", "Popen", "check_output", "check_call"):
        original = getattr(subprocess, call_name)
        monkeypatch.setattr(subprocess, call_name, _guard(call_name, original, attempts))
    yield
    if attempts:
        raise DesktopSideEffectError(
            "test attempted real desktop side effect(s): "
            + "; ".join(attempts)
            + f" [{request.node.nodeid}]. Mock them: patch the module's subprocess.run "
            "(e.g. monkeypatch.setattr('core.tools.web_ops.subprocess.run', fake)) or "
            "patch the tool function at its defining module. Tests must not open "
            "browsers, apps, or change system settings."
        )


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

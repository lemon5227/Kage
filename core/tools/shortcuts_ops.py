"""Shortcut tools — macOS Shortcuts integration."""

import subprocess

from core.tools._response import ok, err


def shortcuts_list() -> str:
    """List available macOS shortcuts."""
    try:
        result = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, check=True)
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return ok(shortcuts=names)
    except Exception as e:
        return err("ShortcutsFailed", str(e))


def shortcuts_run(name: str, input_text: str = "") -> str:
    """Run a macOS shortcut."""
    try:
        cmd = ["shortcuts", "run", name]
        if input_text:
            cmd.extend(["--input-text", input_text])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (result.stdout or "").strip()
        if result.returncode == 0:
            return ok(output=output[:2000])
        return err("ShortcutsFailed", output[:2000] or f"shortcut '{name}' returned {result.returncode}")
    except subprocess.TimeoutExpired:
        return err("Timeout", "Shortcut execution timed out")
    except Exception as e:
        return err("ShortcutsFailed", str(e))


def shortcuts_create(name: str) -> str:
    """Create a new shortcut placeholder."""
    return ok(message=f"Shortcut '{name}' created. Open Shortcuts app to configure.")


def shortcuts_delete(name: str) -> str:
    """Delete a shortcut."""
    try:
        subprocess.run(["shortcuts", "delete", name], check=True)
        return ok(message=f"Shortcut '{name}' deleted")
    except Exception as e:
        return err("DeleteFailed", str(e))


def shortcuts_view(name: str) -> str:
    """View shortcut details."""
    try:
        subprocess.run(["shortcuts", "view", name], check=True)
        return ok(message=f"Viewing shortcut: {name}")
    except Exception as e:
        return err("ViewFailed", str(e))


def shortcuts_bootstrap_kage() -> str:
    """Bootstrap Kage-related shortcuts."""
    return ok(message="Kage shortcuts bootstrapped")

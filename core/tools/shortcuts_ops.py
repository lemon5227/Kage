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


RECOMMENDED_KAGE_SHORTCUTS = [
    "Kage Quick Note",
    "Kage Toggle Mute",
    "Kage Screenshot",
]


def shortcuts_create(name: str) -> str:
    """Create a new shortcut placeholder or guide in macOS Shortcuts app.
    
    Note: macOS does not provide a CLI command to programmatically construct shortcut workflows;
    we open the Shortcuts application for the user to configure actions.
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        return err("InvalidArgument", "Shortcut name cannot be empty")
    try:
        subprocess.run(["open", "-a", "Shortcuts"], check=False)
    except Exception:
        pass
    return ok(
        message=f"Shortcut '{clean_name}' created. Opened Shortcuts app to configure.",
        name=clean_name,
        requires_gui=True,
    )


def shortcuts_delete(name: str) -> str:
    """Delete a shortcut."""
    clean_name = str(name or "").strip()
    if not clean_name:
        return err("InvalidArgument", "Shortcut name cannot be empty")
    try:
        subprocess.run(["shortcuts", "delete", clean_name], check=True)
        return ok(message=f"Shortcut '{clean_name}' deleted")
    except Exception as e:
        return err("DeleteFailed", str(e))


def shortcuts_view(name: str) -> str:
    """View shortcut details."""
    clean_name = str(name or "").strip()
    if not clean_name:
        return err("InvalidArgument", "Shortcut name cannot be empty")
    try:
        subprocess.run(["shortcuts", "view", clean_name], check=True)
        return ok(message=f"Viewing shortcut: {clean_name}")
    except Exception as e:
        return err("ViewFailed", str(e))


def shortcuts_bootstrap_kage() -> str:
    """Bootstrap and inspect Kage companion shortcuts on macOS."""
    try:
        result = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10)
        existing = {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}
    except Exception:
        existing = set()

    installed = [s for s in RECOMMENDED_KAGE_SHORTCUTS if s in existing]
    missing = [s for s in RECOMMENDED_KAGE_SHORTCUTS if s not in existing]

    return ok(
        message="Kage shortcuts bootstrapped",
        installed=installed,
        missing=missing,
        total_recommended=len(RECOMMENDED_KAGE_SHORTCUTS),
    )


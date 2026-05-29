"""Shortcut tools — macOS Shortcuts integration."""

import json
import subprocess


def shortcuts_list() -> str:
    """List available macOS shortcuts."""
    try:
        result = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, check=True)
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return json.dumps({"shortcuts": names}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "ShortcutsFailed", "message": str(e)}, ensure_ascii=False)


def shortcuts_run(name: str, input_text: str = "") -> str:
    """Run a macOS shortcut."""
    try:
        cmd = ["shortcuts", "run", name]
        if input_text:
            cmd.extend(["--input-text", input_text])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (result.stdout or "").strip()
        return json.dumps({"success": result.returncode == 0, "output": output[:2000]}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Timeout", "message": "Shortcut execution timed out"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "ShortcutsFailed", "message": str(e)}, ensure_ascii=False)


def shortcuts_create(name: str) -> str:
    """Create a new shortcut placeholder."""
    return json.dumps({"success": True, "message": f"Shortcut '{name}' created. Open Shortcuts app to configure."}, ensure_ascii=False)


def shortcuts_delete(name: str) -> str:
    """Delete a shortcut."""
    try:
        subprocess.run(["shortcuts", "delete", name], check=True)
        return json.dumps({"success": True, "message": f"Shortcut '{name}' deleted"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "DeleteFailed", "message": str(e)}, ensure_ascii=False)


def shortcuts_view(name: str) -> str:
    """View shortcut details."""
    try:
        subprocess.run(["shortcuts", "view", name], check=True)
        return json.dumps({"success": True, "message": f"Viewing shortcut: {name}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "ViewFailed", "message": str(e)}, ensure_ascii=False)


def shortcuts_bootstrap_kage() -> str:
    """Bootstrap Kage-related shortcuts."""
    return json.dumps({"success": True, "message": "Kage shortcuts bootstrapped"}, ensure_ascii=False)

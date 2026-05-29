"""File operation tools — move, rename, write, trash, search, apply."""

import os
import json
import shutil
import subprocess
import time

from core.undo_log import UndoLog, _move_to_trash

# Blocked system-critical paths
_BLOCKED_PATHS = ("/etc", "/usr", "/bin", "/sbin", "/var", "/System", "/Library", "/private/etc")


def _is_path_allowed(path: str) -> bool:
    """Check if a resolved path is within allowed directories."""
    real = os.path.realpath(path)
    # Block system-critical paths explicitly
    for blocked in _BLOCKED_PATHS:
        if real == blocked or real.startswith(blocked + "/"):
            # Exception: /private/var/folders (macOS temp) and /var/folders are allowed
            if "/var/folders" in real or "/private/var/folders" in real:
                break
            return False
    # Must be under user home or temp directories
    home = os.path.realpath(os.path.expanduser("~"))
    if real == home or real.startswith(home + "/"):
        return True
    # Allow system temp directories (for tests and legitimate temp file ops)
    import tempfile
    tmp = os.path.realpath(tempfile.gettempdir())
    if real == tmp or real.startswith(tmp + "/"):
        return True
    return False


def _validate_path(path: str) -> tuple[str, str | None]:
    """Expand and validate a path. Returns (resolved_path, error_message_or_None)."""
    p = os.path.expanduser(str(path or "").strip())
    if not p:
        return "", "path 不能为空"
    if not _is_path_allowed(p):
        return p, f"路径不在允许范围内: {p}"
    return p, None


def fs_move(src: str, dest_dir: str, workspace_dir: str = "~/.kage") -> str:
    """Move a file/dir into dest_dir (non-destructive). Records undo."""
    s = str(src or "").strip()
    d = str(dest_dir or "").strip()
    if not s or not d:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "src/dest_dir 不能为空"}, ensure_ascii=False)
    s = os.path.expanduser(s)
    d = os.path.expanduser(d)
    s, err = _validate_path(s)
    if err:
        return json.dumps({"success": False, "error": "PathBlocked", "message": err}, ensure_ascii=False)
    d, err = _validate_path(d)
    if err:
        return json.dumps({"success": False, "error": "PathBlocked", "message": err}, ensure_ascii=False)
    if not os.path.exists(s):
        return json.dumps({"success": False, "error": "NotFound", "message": f"未找到: {s}"}, ensure_ascii=False)
    os.makedirs(d, exist_ok=True)
    base = os.path.basename(s.rstrip(os.sep))
    target = os.path.join(d, base)
    if os.path.exists(target):
        target = os.path.join(d, f"{base}.{int(time.time())}")
    undo = UndoLog(workspace_dir=workspace_dir)
    entry_id = undo.append({"type": "fs_move", "ops": [{"op": "move", "src": s, "dst": target}]})
    shutil.move(s, target)
    return json.dumps({"success": True, "moved": {"from": s, "to": target}, "undo_id": entry_id}, ensure_ascii=False)


def fs_rename(path: str, new_name: str, workspace_dir: str = "~/.kage") -> str:
    """Rename a file/dir (non-destructive). Records undo."""
    p = str(path or "").strip()
    nn = str(new_name or "").strip()
    if not p or not nn:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "path/new_name 不能为空"}, ensure_ascii=False)
    p, err = _validate_path(p)
    if err:
        return json.dumps({"success": False, "error": "PathBlocked", "message": err}, ensure_ascii=False)
    if not os.path.exists(p):
        return json.dumps({"success": False, "error": "NotFound", "message": f"未找到: {p}"}, ensure_ascii=False)
    # Prevent directory traversal in new_name
    if "/" in nn or "\\" in nn or nn in (".", ".."):
        return json.dumps({"success": False, "error": "InvalidInput", "message": "new_name 不能包含路径分隔符"}, ensure_ascii=False)
    parent = os.path.dirname(p)
    target = os.path.join(parent, nn)
    if os.path.exists(target):
        return json.dumps({"success": False, "error": "Exists", "message": f"目标已存在: {target}"}, ensure_ascii=False)
    undo = UndoLog(workspace_dir=workspace_dir)
    entry_id = undo.append({"type": "fs_rename", "ops": [{"op": "move", "src": p, "dst": target}]})
    shutil.move(p, target)
    return json.dumps({"success": True, "renamed": {"from": p, "to": target}, "undo_id": entry_id}, ensure_ascii=False)


def fs_write(path: str, content: str, workspace_dir: str = "~/.kage") -> str:
    """Write text to a file. Undoable: backup created before overwrite."""
    p = str(path or "").strip()
    if not p:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "path 不能为空"}, ensure_ascii=False)
    p, err = _validate_path(p)
    if err:
        return json.dumps({"success": False, "error": "PathBlocked", "message": err}, ensure_ascii=False)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    undo = UndoLog(workspace_dir=workspace_dir)
    ops = []
    if os.path.exists(p):
        backup_dir = os.path.join(os.path.expanduser(workspace_dir), "undo", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"{os.path.basename(p)}.{int(time.time())}.bak")
        shutil.copy2(p, backup_path)
        ops.append({"op": "restore", "path": p, "backup": backup_path})
    else:
        ops.append({"op": "created", "path": p})
    entry_id = undo.append({"type": "fs_write", "ops": ops})
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(content or ""))
    return json.dumps({"success": True, "written": p, "undo_id": entry_id}, ensure_ascii=False)


def fs_trash(path: str, workspace_dir: str = "~/.kage") -> str:
    """Move file/dir to Trash (recoverable). Records undo."""
    p = str(path or "").strip()
    if not p:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "path 不能为空"}, ensure_ascii=False)
    p, err = _validate_path(p)
    if err:
        return json.dumps({"success": False, "error": "PathBlocked", "message": err}, ensure_ascii=False)
    if not os.path.exists(p):
        return json.dumps({"success": False, "error": "NotFound", "message": f"未找到: {p}"}, ensure_ascii=False)
    undo = UndoLog(workspace_dir=workspace_dir)
    trashed = _move_to_trash(p)
    entry_id = undo.append({"type": "fs_trash", "ops": [{"op": "untrash", "original": p, "trashed": trashed}]})
    return json.dumps({"success": True, "trashed": trashed, "undo_id": entry_id}, ensure_ascii=False)


def fs_undo_last(workspace_dir: str = "~/.kage") -> str:
    """Undo the last recorded filesystem operation."""
    undo = UndoLog(workspace_dir=workspace_dir)
    return json.dumps(undo.undo_last(), ensure_ascii=False)


def fs_search(query: str, kind: str = "any", max_results: int = 20, scope: list[str] | None = None) -> str:
    """Search files/folders using Spotlight (macOS)."""
    q = str(query or "").strip()
    if not q:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "query 为空"}, ensure_ascii=False)
    k = str(kind or "any").strip().lower()
    if k not in ("any", "file", "dir"):
        k = "any"
    limit = max(1, min(200, int(max_results or 20)))
    cmd = ["mdfind", "-name", q]
    scopes = [os.path.expanduser(str(s)) for s in scope if str(s).strip()] if scope else []
    results: list[str] = []
    seen: set[str] = set()

    def _run(one_scope: str | None):
        args = ["mdfind", "-onlyin", one_scope, "-name", q] if one_scope else list(cmd)
        try:
            out = subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return []
        return [line.strip() for line in (out or "").splitlines() if line.strip()]

    batches = [_run(s) for s in scopes if os.path.isdir(s)] if scopes else [_run(None)]
    for batch in batches:
        for p in batch:
            if p in seen:
                continue
            seen.add(p)
            if k == "dir" and not os.path.isdir(p):
                continue
            if k == "file" and not os.path.isfile(p):
                continue
            results.append(p)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return json.dumps({"success": True, "results": results}, ensure_ascii=False)


def fs_preview(ops: list[dict]) -> str:
    """Preview a generic file operation plan."""
    if not isinstance(ops, list) or not ops:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "ops 为空"}, ensure_ascii=False)
    summary = []
    has_trash = False
    for op in ops[:200]:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op") or "").strip().lower()
        if kind == "move":
            summary.append({"op": "move", "src": op.get("src"), "dest_dir": op.get("dest_dir")})
        elif kind == "rename":
            summary.append({"op": "rename", "path": op.get("path"), "new_name": op.get("new_name")})
        elif kind == "write":
            content = str(op.get("content") or "")
            summary.append({"op": "write", "path": op.get("path"), "bytes": len(content.encode("utf-8"))})
        elif kind == "trash":
            has_trash = True
            summary.append({"op": "trash", "path": op.get("path")})
    return json.dumps({"success": True, "has_trash": has_trash, "ops": summary}, ensure_ascii=False)


def fs_apply(ops: list[dict], workspace_dir: str = "~/.kage") -> str:
    """Apply a generic file operation plan (undoable)."""
    if not isinstance(ops, list) or not ops:
        return json.dumps({"success": False, "error": "InvalidInput", "message": "ops 不能为空"}, ensure_ascii=False)

    undo = UndoLog(workspace_dir=workspace_dir)
    applied = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op") or "").strip().lower()
        if kind == "move":
            src, err = _validate_path(str(op.get("src", "")))
            if err:
                continue
            dest_dir, err = _validate_path(str(op.get("dest_dir", "")))
            if err:
                continue
            if not src or not dest_dir or not os.path.exists(src):
                continue
            os.makedirs(dest_dir, exist_ok=True)
            base = os.path.basename(src.rstrip(os.sep))
            target = os.path.join(dest_dir, base)
            if os.path.exists(target):
                target = os.path.join(dest_dir, f"{base}.{int(time.time())}")
            shutil.move(src, target)
            applied.append({"op": "move", "src": src, "dst": target})
        elif kind == "rename":
            path, err = _validate_path(str(op.get("path", "")))
            if err:
                continue
            new_name = str(op.get("new_name", ""))
            if not path or not new_name or not os.path.exists(path):
                continue
            if "/" in new_name or "\\" in new_name:
                continue
            parent = os.path.dirname(path)
            target = os.path.join(parent, new_name)
            if os.path.exists(target):
                continue
            shutil.move(path, target)
            applied.append({"op": "rename", "src": path, "dst": target})
        elif kind == "write":
            path, err = _validate_path(str(op.get("path", "")))
            if err:
                continue
            content = str(op.get("content", ""))
            if not path:
                continue
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            applied.append({"op": "write", "path": path})
        elif kind == "trash":
            path, err = _validate_path(str(op.get("path", "")))
            if err:
                continue
            if not path or not os.path.exists(path):
                continue
            trashed = _move_to_trash(path)
            applied.append({"op": "trash", "path": path, "trashed": trashed})

    if applied:
        entry_id = undo.append({"type": "fs_apply", "ops": applied})
        return json.dumps({"success": True, "applied": len(applied), "undo_id": entry_id}, ensure_ascii=False)
    return json.dumps({"success": False, "error": "NoOpsApplied", "message": "没有可执行的操作"}, ensure_ascii=False)

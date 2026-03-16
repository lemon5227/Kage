"""core.undo_log

Minimal file-operation undo log.

Design goals:
- Keep assistant non-blocking (no confirmation for non-delete operations).
- Make changes reversible when possible by recording a compact JSONL log.
- Avoid overwriting existing files during undo (use conflict suffix).

This module intentionally stays small and dependency-free.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import uuid


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _unique_conflict_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        candidate = f"{base}.conflict-{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
    return f"{base}.conflict-{uuid.uuid4().hex[:8]}{ext}"


class UndoLog:
    def __init__(self, workspace_dir: str = "~/.kage"):
        self.workspace_dir = os.path.expanduser(workspace_dir)
        self.undo_dir = os.path.join(self.workspace_dir, "undo")
        self.backups_dir = os.path.join(self.undo_dir, "backups")
        self.log_path = os.path.join(self.undo_dir, "ops.jsonl")
        _ensure_dir(self.undo_dir)
        _ensure_dir(self.backups_dir)

    def append(self, entry: dict) -> str:
        entry_id = entry.get("id") or uuid.uuid4().hex
        entry = dict(entry)
        entry["id"] = entry_id
        entry.setdefault("ts", _now_iso())
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            # Best-effort: if we can't log, still allow the op.
            pass
        return str(entry_id)

    def _read_last_entry(self) -> dict | None:
        if not os.path.isfile(self.log_path):
            return None
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                continue
        return None

    def undo_last(self) -> dict:
        entry = self._read_last_entry()
        if not entry:
            return {"success": False, "error": "EmptyUndoLog", "message": "没有可撤销的记录"}
        return self.undo_entry(entry)

    def undo_entry(self, entry: dict) -> dict:
        ops = entry.get("ops")
        if not isinstance(ops, list) or not ops:
            return {"success": False, "error": "InvalidEntry", "message": "撤销记录不完整"}

        # Undo in reverse order
        undone = []
        for op in reversed(ops):
            if not isinstance(op, dict):
                continue
            kind = op.get("op")
            try:
                if kind == "move":
                    src = str(op.get("src") or "")
                    dst = str(op.get("dst") or "")
                    if not dst or not os.path.exists(dst):
                        undone.append({"op": kind, "status": "skipped", "reason": "dst_missing"})
                        continue
                    # Avoid overwriting
                    target = src
                    if target and os.path.exists(target):
                        target = _unique_conflict_path(target)
                    if target:
                        _ensure_dir(os.path.dirname(target))
                        shutil.move(dst, target)
                        undone.append({"op": kind, "status": "ok", "from": dst, "to": target})
                    else:
                        undone.append({"op": kind, "status": "skipped", "reason": "src_empty"})
                elif kind == "restore":
                    path = str(op.get("path") or "")
                    backup = str(op.get("backup") or "")
                    if not path or not backup or not os.path.exists(backup):
                        undone.append({"op": kind, "status": "skipped", "reason": "backup_missing"})
                        continue
                    _ensure_dir(os.path.dirname(path))
                    shutil.copy2(backup, path)
                    undone.append({"op": kind, "status": "ok", "path": path})
                elif kind == "untrash":
                    original = str(op.get("original") or "")
                    trashed = str(op.get("trashed") or "")
                    if not original or not trashed or not os.path.exists(trashed):
                        undone.append({"op": kind, "status": "skipped", "reason": "trashed_missing"})
                        continue
                    target = original
                    if os.path.exists(target):
                        target = _unique_conflict_path(target)
                    _ensure_dir(os.path.dirname(target))
                    shutil.move(trashed, target)
                    undone.append({"op": kind, "status": "ok", "to": target})
                elif kind == "created":
                    path = str(op.get("path") or "")
                    # For undo, we move created file to Trash if possible.
                    if path and os.path.exists(path):
                        trashed = _move_to_trash(path)
                        undone.append({"op": kind, "status": "ok", "trashed": trashed})
                    else:
                        undone.append({"op": kind, "status": "skipped", "reason": "missing"})
                else:
                    undone.append({"op": str(kind), "status": "skipped", "reason": "unknown_op"})
            except Exception as exc:
                undone.append({"op": str(kind), "status": "error", "error": str(exc)})

        return {"success": True, "entry_id": entry.get("id"), "undone": undone}


def _trash_dir() -> str:
    # macOS uses ~/.Trash; other platforms can use a local .Trash fallback.
    home = os.path.expanduser("~")
    mac = os.path.join(home, ".Trash")
    if os.path.isdir(mac):
        return mac
    fallback = os.path.join(home, ".kage", ".Trash")
    _ensure_dir(fallback)
    return fallback


def _move_to_trash(path: str) -> str:
    td = _trash_dir()
    base = os.path.basename(path.rstrip(os.sep))
    target = os.path.join(td, base)
    if os.path.exists(target):
        target = os.path.join(td, f"{base}.{uuid.uuid4().hex[:8]}")
    shutil.move(path, target)
    return target

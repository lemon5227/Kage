"""Small local-storage primitives shared by Kage's on-disk state (logs, caches, indexes).

- atomic_write_text: temp file in the same directory + fsync + rename, so readers never see half a file and
  a crash leaves the previous version (plain write_text truncated a file it was rewriting if killed mid-way).
- file_lock: an advisory cross-process lock (flock) for read-modify-write cycles; two Kage servers did run at
  once on 10-25 and wrote the same usage log.
- private_dir: create a directory readable only by the user (usage logs hold requests and mail subjects).
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import tempfile


def private_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def atomic_write_text(path: Path, text: str, *, private: bool = False) -> None:
    path = Path(path)
    if private:
        private_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if private:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_line(path: Path, line: str, *, private: bool = False) -> None:
    """Append one line under the file's lock (O_APPEND alone does not keep long lines from two processes whole)."""
    path = Path(path)
    if private:
        private_dir(path.parent)
    with file_lock(path):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600 if private else 0o644)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream:
            stream.write(line if line.endswith('\n') else line + '\n')


@contextmanager
def file_lock(path: Path):
    """Exclusive advisory lock on `<path>.lock` for the duration of the block (works across processes)."""
    lock_path = Path(path).with_name(f'.{Path(path).name}.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, 'w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

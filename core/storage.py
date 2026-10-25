"""Atomic JSON storage shared by settings and memory.

Transactions serialize readers/writers inside this process. Invalid existing
data is never replaced with an empty document by a setter.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def file_lock(path: Path):
    key = str(Path(path).resolve()).casefold() if os.name == "nt" else str(Path(path).resolve())
    with _guard:
        return _locks.setdefault(key, threading.RLock())


def read_json(path: Path, default_factory=dict):
    path = Path(path)
    with file_lock(path):
        if not path.exists():
            return default_factory()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, type(default_factory())):
            raise ValueError(f"Invalid document in {path.name}; original file preserved")
        return data


def write_json(path: Path, data) -> None:
    path = Path(path)
    payload = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    with file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Windows scanners/sync clients can briefly open the destination
            # without delete sharing. Retry the same atomic replacement; a
            # permanent denial still raises with the original file intact.
            for attempt in range(5):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError as exc:
                    if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 4:
                        raise
                    time.sleep(0.02 * (2 ** attempt))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def update_json(path: Path, change, default_factory=dict):
    with file_lock(path):
        data = read_json(path, default_factory)
        result = change(data)
        write_json(path, data)
        return result

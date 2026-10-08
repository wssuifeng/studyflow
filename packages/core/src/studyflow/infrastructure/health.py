"""Non-destructive, explainable filesystem access diagnostics."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_probe(path: Path) -> dict:
    probe = None
    phase = "create"
    if not path.is_dir():
        return {"writable": False, "reason": "directory_missing", "phase": phase}
    try:
        fd, name = tempfile.mkstemp(prefix=".studyflow-write-check-", dir=path)
        probe = Path(name)
        # Creating an empty file can succeed even when no data can be persisted.
        with os.fdopen(fd, "wb") as stream:
            phase = "write"
            stream.write(b"StudyFlow write check\n")
            stream.flush()
            os.fsync(stream.fileno())
        phase = "cleanup"
        probe.unlink()
        probe = None
        return {"writable": True, "reason": "verified", "phase": "complete"}
    except OSError as exc:
        full = exc.errno == 28 or getattr(exc, "winerror", None) in {39, 112}
        return {"writable": False, "reason": "disk_full" if full else "permission_denied" if isinstance(exc, PermissionError) else "filesystem_error",
                "phase": phase, "errno": exc.errno, "winerror": getattr(exc, "winerror", None)}
    finally:
        if probe is not None:
            try:
                probe.unlink()
            except OSError:
                pass


def sqlite_write_probe(path: Path) -> dict:
    directory = write_probe(path.parent)
    if not directory["writable"]:
        return {**directory, "scope": "database_directory"}
    if not path.exists():
        return {"writable": True, "reason": "not_initialized", "scope": "database"}
    try:
        fd = os.open(path, os.O_RDWR)
        os.close(fd)
        return {"writable": True, "reason": "file_access_verified", "scope": "database"}
    except OSError as exc:
        return {"writable": False, "reason": "permission_denied" if isinstance(exc, PermissionError) else "filesystem_error",
                "scope": "database", "errno": exc.errno, "winerror": getattr(exc, "winerror", None)}

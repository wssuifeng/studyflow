from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
from traceback import extract_tb
from uuid import uuid4


def record_engine_error(log_root: Path, error: Exception) -> dict[str, str | bool]:
    """Persist stack locations, never exception messages, SQL, answers or locals."""
    diagnostic_id = str(uuid4())
    entry = {
        "diagnostic_id": diagnostic_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exception_type": type(error).__name__,
        "frames": [{"file": Path(frame.filename).name, "line": frame.lineno,
                    "function": frame.name} for frame in extract_tb(error.__traceback__)],
    }
    original=getattr(error,"orig",error)
    if isinstance(getattr(original,"sqlite_errorcode",None),int):
        entry["sqlite_error_code"]=original.sqlite_errorcode
        entry["sqlite_error_name"]=getattr(original,"sqlite_errorname",None)
    # Only a validated list of schema identifiers; never the message or SQL parameters.
    match=re.fullmatch(r"UNIQUE constraint failed: ([A-Za-z0-9_., ]+)",str(original))
    if match: entry["constraint_columns"]=match.group(1).split(", ")
    if isinstance(error, ModuleNotFoundError) and error.name and re.fullmatch(r"[A-Za-z0-9_.]+", error.name):
        entry["missing_module"] = error.name
    path = log_root / "engine-errors.jsonl"
    try:
        log_root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        return {"diagnostic_id": diagnostic_id, "diagnostic_unavailable": True,
                "log_write_error": "disk_full" if exc.errno == 28 or getattr(exc, "winerror", None) in {39, 112} else "filesystem_error"}
    return {"diagnostic_id": diagnostic_id, "log_path": str(path)}

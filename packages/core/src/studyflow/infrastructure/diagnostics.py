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
    if isinstance(error, ModuleNotFoundError) and error.name and re.fullmatch(r"[A-Za-z0-9_.]+", error.name):
        entry["missing_module"] = error.name
    path = log_root / "engine-errors.jsonl"
    try:
        log_root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return {"diagnostic_id": diagnostic_id, "diagnostic_unavailable": True}
    return {"diagnostic_id": diagnostic_id, "log_path": str(path)}

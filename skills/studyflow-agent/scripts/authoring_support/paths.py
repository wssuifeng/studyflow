from __future__ import annotations
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Workspace:
    """An explicit author-material boundary, not an application data workspace."""
    def __init__(self, root):
        absolute=Path(root).absolute()
        if not absolute.is_dir():
            raise ValueError("ROOT_REQUIRED: existing author-material root required")
        self.root=absolute.resolve()
        if self.root.name == "local.studyflow.desktop" or (self.root/".studyflow").exists():
            raise ValueError("DATA_WORKSPACE: do not run author helpers on an application data root")
        self.path(absolute)

    def path(self, value):
        path=Path(value)
        absolute=path.absolute() if path.is_absolute() else (self.root/path).absolute()
        resolved=absolute.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("PATH_BOUNDARY: path must stay inside the explicit author root")
        current=absolute
        while True:
            if current.is_symlink() or (hasattr(current,"is_junction") and current.is_junction()):
                raise ValueError("LINKED_PATH: linked author resources are not accepted")
            if current==self.root or current.parent==current:
                break
            current=current.parent
        return resolved

    def json(self, value, max_bytes=262144):
        path=self.path(value)
        if path.stat().st_size>max_bytes:
            raise ValueError("INPUT_BUDGET: split the selected input")
        result=json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(result,dict):
            raise ValueError("FORMAT: expected a JSON object")
        return result

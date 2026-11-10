"""Read-only discovery of runtime-owned Agent entry paths; no config or PATH edits."""
import json
from pathlib import Path
import sys
import hashlib

def workspace_key(workspace):
    return hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:16]


def _within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _overlaps(path, other):
    return _within(path, other) or _within(other, path)


def _agent_workspace_entry(pointer_path, forbidden_roots):
    try:
        pointer_path.stat()
    except FileNotFoundError:
        return (None, "invalid") if pointer_path.is_symlink() else (None, "missing")
    except OSError:
        return None, "invalid"

    try:
        if pointer_path.is_symlink() or not pointer_path.is_file() or pointer_path.stat().st_size > 16_384:
            return None, "invalid"
        payload = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or type(payload.get("format")) is not int or payload["format"] != 1:
            return None, "invalid"
        root_value = payload.get("agent_workspace")
        if not isinstance(root_value, str) or not root_value.strip():
            return None, "invalid"
        candidate = Path(root_value)
        if not candidate.is_absolute():
            return None, "invalid"
        root = candidate.resolve(strict=True)
        if not root.is_dir():
            return None, "invalid"
        for forbidden in forbidden_roots:
            if _overlaps(root, forbidden.resolve()):
                return None, "invalid"
        entry = (root / "AGENTS.md").resolve(strict=True)
        if entry.parent != root or not entry.is_file():
            return None, "invalid"
        return str(entry), "found"
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return None, "invalid"


def installation_info(settings, *, executable=None, frozen=None, source_root=None, agent_workspace_pointer=None):
    binary=Path(executable or sys.executable).resolve()
    installed=getattr(sys,"frozen",False) if frozen is None else frozen
    workspace=settings.workspace_root.resolve()
    if installed:
        cli=binary.with_name("studyflow.exe")
        skill=binary.parent/"studyflow-agent"/"SKILL.md"
        argv=[str(cli)];kind="installed";available=cli.is_file()
    else:
        root=Path(source_root).resolve() if source_root else Path(__file__).resolve().parents[5]
        skill=root/"skills"/"studyflow-agent"/"SKILL.md"
        cli=None;argv=[str(binary),"-m","studyflow"];kind="repository"
        available=binary.is_file() and (root/"packages/core/src/studyflow/__main__.py").is_file()
    skill_exists=skill.is_file()
    forbidden_roots=[workspace]
    if installed:
        forbidden_roots.extend([binary.parent, binary.parent.parent])
    else:
        forbidden_roots.append(root)
    pointer=Path(agent_workspace_pointer) if agent_workspace_pointer else Path.home()/".studyflow-agent"/"workspace.json"
    agent_entry,agent_status=_agent_workspace_entry(pointer,forbidden_roots)
    return {"workspace":str(workspace),"workspace_exists":workspace.is_dir(),
        "cli_path":str(cli) if cli else None,"cli_argv":argv,"cli_available":available,
        "skill_path":str(skill),"skill_kind":kind,"skill_available":skill_exists,
        "agent_workspace_entry_path":agent_entry,"agent_workspace_entry_status":agent_status,
        "source_cli":not installed,"automatic_path":False,
        "agent_ready":available and skill_exists and workspace.is_dir()}

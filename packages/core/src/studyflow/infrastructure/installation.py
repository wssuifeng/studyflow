"""Read-only discovery of runtime-owned Agent entry paths; no config or PATH edits."""
from pathlib import Path
import sys
import hashlib

def workspace_key(workspace):
    return hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:16]


def installation_info(settings, *, executable=None, frozen=None, source_root=None):
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
    return {"workspace":str(workspace),"workspace_exists":workspace.is_dir(),
        "cli_path":str(cli) if cli else None,"cli_argv":argv,"cli_available":available,
        "skill_path":str(skill),"skill_kind":kind,"skill_available":skill_exists,
        "source_cli":not installed,"automatic_path":False,
        "agent_ready":available and skill_exists and workspace.is_dir()}

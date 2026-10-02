"""Read-only bundled assets, kept separate from mutable learning workspaces."""
from pathlib import Path
import sys


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        root = Path(frozen)
        bundled = root / "studyflow" / "resources"
        return bundled if bundled.is_dir() else root
    return package_root() / "resources"


def default_workspace_root() -> Path:
    """Editable source keeps its development default; installed code is not data."""
    source_root = package_root().parent
    if source_root.name == "src" and (source_root.parent / "pyproject.toml").is_file():
        return source_root.parent
    # Desktop sets STUDYFLOW_WORKSPACE explicitly. Standalone installed CLI
    # defaults to cwd, never site-packages or the frozen extraction directory.
    return Path.cwd()


def ensure_demo_content(workspace_root: Path) -> None:
    """Only explicit demo initialization copies its bundled, synthetic example."""
    source = resource_root() / "content" / "lessons" / "java-reference.md"
    target = workspace_root / "content" / "lessons" / "java-reference.md"
    if target.exists() or target.is_symlink():
        return  # Existing notes belong to the learner, even if they are links.
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents overwriting a file created concurrently.
    try:
        with target.open("xb") as destination:
            destination.write(source.read_bytes())
    except FileExistsError:
        pass

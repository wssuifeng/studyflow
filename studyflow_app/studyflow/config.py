from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    database_url: str
    host: str = "127.0.0.1"
    port: int = 8787

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> "Settings":
        package_root = Path(__file__).resolve().parents[1]
        default_root = base_dir or Path(os.getenv("STUDYFLOW_WORKSPACE", package_root))
        root = Path(os.getenv("STUDYFLOW_WORKSPACE", default_root)).expanduser().resolve()
        database_url = os.getenv("STUDYFLOW_DATABASE_URL")
        if not database_url:
            database_path = os.getenv("STUDYFLOW_DATABASE_PATH")
            if database_path:
                database_url = f"sqlite:///{Path(database_path).expanduser().resolve().as_posix()}"
            else:
                # Preserve the existing development database when the desktop app
                # uses the repository root as its content workspace. New workspaces
                # keep runtime state under .studyflow instead of polluting the root.
                legacy_path = package_root / "studyflow.db"
                managed_path = root / ".studyflow" / "studyflow.db"
                # Keep the legacy database only for the package workspace itself.
                # A newly selected/imported workspace must never attach to the
                # development database merely because it exists beside the package.
                selected_path = legacy_path if root == package_root and legacy_path.exists() else managed_path
                database_url = f"sqlite:///{selected_path.as_posix()}"
        return cls(
            workspace_root=root,
            database_url=database_url,
            host=os.getenv("STUDYFLOW_HOST", "127.0.0.1"),
            port=int(os.getenv("STUDYFLOW_PORT", "8787")),
        )

    @property
    def content_root(self) -> Path:
        return self.workspace_root / "content"

    @property
    def templates_root(self) -> Path:
        return self.workspace_root / "templates"

    @property
    def static_root(self) -> Path:
        return self.workspace_root / "static"

    @property
    def runtime_root(self) -> Path:
        """Application-managed runtime state that moves with a workspace."""
        return self.workspace_root / ".studyflow"

    @property
    def backup_root(self) -> Path:
        return self.runtime_root / "backups"

    @property
    def log_root(self) -> Path:
        return self.runtime_root / "logs"

    @property
    def database_path(self) -> Path | None:
        """Resolve a SQLite URL to a filesystem path without opening it."""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw = unquote(self.database_url[len(prefix):])
        if raw in {":memory:", ""}:
            return None
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (self.workspace_root / path).resolve()

    @property
    def uses_managed_sqlite(self) -> bool:
        path = self.database_path
        return path is not None and path == (self.runtime_root / "studyflow.db").resolve()

    def ensure_layout(self) -> None:
        """Create portable runtime directories, never user documents outside content."""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.content_root.mkdir(parents=True, exist_ok=True)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)

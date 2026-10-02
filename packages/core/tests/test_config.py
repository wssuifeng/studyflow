from pathlib import Path

from studyflow.config import Settings


def test_workspace_root_can_use_explicit_database_path(monkeypatch, tmp_path):
    database = tmp_path / "runtime" / "studyflow.db"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("STUDYFLOW_DATABASE_PATH", str(database))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    settings = Settings.from_env()
    assert settings.workspace_root == tmp_path.resolve()
    assert settings.database_url == f"sqlite:///{database.resolve().as_posix()}"

"""Bundled immutable assets must work outside the old source directory."""
import sys

from fastapi.testclient import TestClient
from studyflow.config import Settings
from studyflow.infrastructure.resources import default_workspace_root, resource_root
from studyflow.seed import seed
from studyflow.web import create_app


def test_package_assets_are_complete():
    root = resource_root()
    for name in ("alembic.ini", "templates/today.html", "static/app.css", "content/lessons/java-reference.md"):
        assert (root / name).is_file(), name
    assert sorted(path.name for path in (root / "migrations/versions").glob("[0-9]*.py")) == [
        "0001_mvp_baseline.py", "0002_generic_metadata.py", "0003_learning_console_lifecycle.py",
        "0004_learning_progress.py", "0005_course_answers.py", "0006_course_study.py", "0007_learning_tools.py", "0008_plan_notebooks.py", "0009_write_contract.py", "0010_review_tasks.py", "0011_course_revisions.py", "0012_plan_management.py",
    ]


def test_default_workspace_is_not_the_read_only_asset_directory():
    assert default_workspace_root() != resource_root()


def test_frozen_assets_resolve_within_the_bundle(tmp_path, monkeypatch):
    bundled = tmp_path / "studyflow/resources"
    bundled.mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_root() == bundled


def test_compatibility_web_uses_package_assets_in_a_new_workspace(app_service):
    app_service.seed_demo()
    client = TestClient(create_app(settings=app_service.settings, service=app_service))
    assert client.get("/today").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_demo_initialization_copies_the_example_without_overwriting(tmp_path):
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    seed(settings)
    document = tmp_path / "content/lessons/java-reference.md"
    assert document.is_file()
    document.write_text("User-owned note", encoding="utf-8")
    seed(settings)
    assert document.read_text(encoding="utf-8") == "User-owned note"

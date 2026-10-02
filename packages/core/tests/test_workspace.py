from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from studyflow.config import Settings
from studyflow.db import build_engine, init_db
from studyflow.domain import DomainError
from studyflow.workspace import export_workspace, restore_workspace


def _workspace(tmp_path: Path) -> Settings:
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{(tmp_path / '.studyflow' / 'studyflow.db').as_posix()}")
    settings.ensure_layout()
    engine = build_engine(settings)
    init_db(engine)
    engine.dispose()
    return settings


def _rewrite_archive(source: Path, target: Path, mutate_manifest=None, omit: str | None = None, replace: dict[str, bytes] | None = None) -> None:
    with zipfile.ZipFile(source, "r") as reader:
        manifest = json.loads(reader.read("manifest.json").decode("utf-8"))
        if mutate_manifest:
            mutate_manifest(manifest)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as writer:
            for info in reader.infolist():
                if info.filename == omit:
                    continue
                payload = replace.get(info.filename) if replace and info.filename in replace else reader.read(info.filename)
                if info.filename == "manifest.json":
                    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                writer.writestr(info, payload)


def test_settings_new_workspace_never_reuses_package_database(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    settings = Settings.from_env()
    assert settings.database_path == (tmp_path / ".studyflow" / "studyflow.db").resolve()
    assert settings.uses_managed_sqlite is True


def test_workspace_export_and_atomic_restore_round_trip(tmp_path):
    source_root = tmp_path / "source"
    settings = _workspace(source_root)
    lesson = source_root / "content" / "lessons" / "portable.md"
    lesson.parent.mkdir(parents=True, exist_ok=True)
    lesson.write_text("# Portable lesson\n\nKeep this Markdown.\n", encoding="utf-8")
    archive = tmp_path / "backups" / "portable.zip"

    exported = export_workspace(settings, archive)
    assert archive.exists()
    assert exported["format_version"] == "1"
    assert exported["file_count"] == 1
    assert exported["manifest"]["files"][0]["relative_path"] == "content/lessons/portable.md"

    target = tmp_path / "restored"
    restored = restore_workspace(archive, target)
    assert restored["replaced_existing"] is False
    assert (target / ".studyflow" / "studyflow.db").exists()
    assert (target / "content" / "lessons" / "portable.md").read_text(encoding="utf-8") == lesson.read_text(encoding="utf-8")
    connection = sqlite3.connect(target / ".studyflow" / "studyflow.db")
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='courses'").fetchone()
    connection.close()


def test_restore_preserves_existing_workspace_on_successful_replacement(tmp_path):
    settings = _workspace(tmp_path / "source")
    (settings.content_root / "lesson.md").write_text("source", encoding="utf-8")
    archive = tmp_path / "source.zip"
    export_workspace(settings, archive)

    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("do not delete", encoding="utf-8")
    restored = restore_workspace(archive, target)
    previous = Path(restored["previous_workspace"])
    assert previous.exists()
    assert (previous / "keep.txt").read_text(encoding="utf-8") == "do not delete"
    assert not (target / "keep.txt").exists()


def test_restore_rejects_unknown_schema_without_touching_target(tmp_path):
    settings = _workspace(tmp_path / "source")
    archive = tmp_path / "source.zip"
    export_workspace(settings, archive)
    broken = tmp_path / "unknown-schema.zip"
    _rewrite_archive(archive, broken, mutate_manifest=lambda manifest: manifest.__setitem__("schema_revision", "9999_future"))
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("original", encoding="utf-8")

    with pytest.raises(DomainError) as error:
        restore_workspace(broken, target)
    assert error.value.code == "UNKNOWN_SCHEMA"
    assert marker.read_text(encoding="utf-8") == "original"


def test_restore_rejects_missing_markdown_without_touching_target(tmp_path):
    settings = _workspace(tmp_path / "source")
    (settings.content_root / "lesson.md").write_text("lesson", encoding="utf-8")
    archive = tmp_path / "source.zip"
    export_workspace(settings, archive)
    broken = tmp_path / "missing-file.zip"
    _rewrite_archive(archive, broken, omit="files/content/lesson.md")
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("original", encoding="utf-8")

    with pytest.raises(DomainError) as error:
        restore_workspace(broken, target)
    assert error.value.code == "BACKUP_FILE_MISSING"
    assert marker.read_text(encoding="utf-8") == "original"


def test_restore_rejects_hash_mismatch_without_touching_target(tmp_path):
    settings = _workspace(tmp_path / "source")
    (settings.content_root / "lesson.md").write_text("lesson", encoding="utf-8")
    archive = tmp_path / "source.zip"
    export_workspace(settings, archive)
    broken = tmp_path / "hash-mismatch.zip"
    _rewrite_archive(archive, broken, replace={"files/content/lesson.md": b"tampered"})
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("original", encoding="utf-8")

    with pytest.raises(DomainError) as error:
        restore_workspace(broken, target)
    assert error.value.code == "BACKUP_HASH_MISMATCH"
    assert marker.read_text(encoding="utf-8") == "original"


def test_export_rejects_missing_registered_markdown(tmp_path):
    settings = _workspace(tmp_path / "source")
    registered = settings.content_root / "registered.md"
    registered.write_text("registered", encoding="utf-8")
    connection = sqlite3.connect(settings.database_path)
    connection.execute(
        "INSERT INTO documents (id, relative_path, document_type, status, file_size, content_hash, summary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("doc-1", "content/registered.md", "MARKDOWN", "PRESENT", registered.stat().st_size, "", ""),
    )
    connection.commit()
    connection.close()
    registered.unlink()

    with pytest.raises(DomainError) as error:
        export_workspace(settings, tmp_path / "broken.zip")
    assert error.value.code == "DOCUMENT_MISSING"

from __future__ import annotations

from sqlalchemy import func, select

from studyflow.engine import StudyFlowEngine
from studyflow.infrastructure.persistence.base import EventLog
from studyflow.models import Submission
from test_course_answers import multi_course


def test_same_draft_can_be_saved_many_times_and_submitted(app_service, multi_course):
    course_id, exercise_ids = multi_course
    engine = StudyFlowEngine(service=app_service)
    draft = None
    for revision in range(4):
        entry = {"exercise_id": exercise_ids[0], "answer_text": f"isolated answer revision {revision}"}
        if draft:
            entry.update(submission_id=draft["id"], expected_version=draft["version"])
        params = {"course_id": course_id, "answers": [entry], "idempotency_key": f"autosave-{revision}"}
        response = engine.handle({"id": revision, "method": "course.answers.draft.save", "params": params})
        assert response["ok"], response
        draft = response["data"]["submissions"][0]
        replayed = engine.handle({"id": 90 + revision, "method": "course.answers.draft.save", "params": params})
        assert replayed["data"] == response["data"]
    params = {
        "course_id": course_id,
        "answers": [
            {"exercise_id": exercise_ids[0], "submission_id": draft["id"],
             "expected_version": draft["version"], "answer_text": "final isolated answer"},
            {"exercise_id": exercise_ids[1], "answer_text": "second isolated answer"},
        ],
        "idempotency_key": "final-submit",
    }
    response = engine.handle({"id": 5, "method": "course.answers.submit", "params": params})
    assert response["ok"], response
    assert response["data"]["status"] == "WAITING_REVIEW"
    with app_service.session() as db:
        assert db.scalar(select(func.count(Submission.id))) == 2
        assert db.scalar(select(func.count(EventLog.id)).where(EventLog.action == "DRAFT_SAVE")) == 4


def test_0006_auto_upgrade_preserves_events_and_removes_signature(tmp_path):
    import sqlite3
    from alembic import command
    from studyflow.config import Settings
    from studyflow.db import build_engine, init_db
    from studyflow.infrastructure.persistence.migrations import _alembic_config

    path = tmp_path / "old.db"
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{path.as_posix()}")
    command.upgrade(_alembic_config(settings), "0006_course_study")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO event_logs (id,source,object_type,object_id,action,summary) VALUES ('old','USER_WEB','submission','s','DRAFT_SAVE','draft saved')")
        db.execute("INSERT INTO courses (id,title) VALUES ('c','isolated legacy course')")
        db.execute("INSERT INTO lessons (id,course_id,title,markdown_path) VALUES ('l','c','lesson','old.md')")
        db.execute("INSERT INTO exercises (id,lesson_id,title,prompt) VALUES ('e','l','exercise','prompt')")
        db.execute("INSERT INTO submissions (id,exercise_id,answer_text,status) VALUES ('s','e','preserved synthetic answer','DRAFT')")
    engine = build_engine(settings)
    try:
        init_db(engine)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT answer_text FROM submissions WHERE id='s'").fetchone()[0] == "preserved synthetic answer"
            assert db.execute("SELECT summary FROM event_logs WHERE id='old'").fetchone()[0] == "draft saved"
            db.execute("INSERT INTO event_logs (id,source,object_type,object_id,action,summary) VALUES ('new','USER_WEB','submission','s','DRAFT_SAVE','draft saved')")
            assert db.execute("SELECT count(*) FROM event_logs").fetchone()[0] == 2
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0012_plan_management"
        backups = list(tmp_path.glob("old.backup-*.db"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("SELECT count(*) FROM event_logs").fetchone()[0] == 1
        init_db(engine)
        assert len(list(tmp_path.glob("old.backup-*.db"))) == 1
    finally:
        engine.dispose()


def test_doctor_marks_denied_workspace_unhealthy(app_service, monkeypatch):
    from studyflow.infrastructure import health
    monkeypatch.setattr(health, "write_probe", lambda path: {"writable": False, "reason": "permission_denied", "phase": "create"})
    response = StudyFlowEngine(service=app_service).handle({"id": 1, "method": "system.doctor"})
    assert response["ok"]
    assert response["data"]["healthy"] is False
    assert response["data"]["workspace"]["writable"] is False
    assert response["data"]["database"]["writable"] is False


def test_database_errors_are_classified_without_exposing_answers(tmp_path):
    import json
    import sqlite3
    from sqlalchemy.exc import IntegrityError, OperationalError
    from studyflow.infrastructure.errors import database_error_payload
    from studyflow.infrastructure.diagnostics import record_engine_error

    for code, expected in ((sqlite3.SQLITE_READONLY, "DATABASE_READ_ONLY"), (sqlite3.SQLITE_BUSY, "DATABASE_LOCKED"), (sqlite3.SQLITE_FULL, "DATABASE_DISK_FULL")):
        original = sqlite3.OperationalError("do not expose synthetic secret")
        original.sqlite_errorcode = code
        error = OperationalError("private SQL", {"answer": "synthetic secret"}, original)
        payload = database_error_payload(error)
        assert payload["code"] == expected
        assert "synthetic secret" not in json.dumps(payload)
    error = IntegrityError("private SQL", {"answer": "synthetic secret"}, sqlite3.IntegrityError("UNIQUE constraint failed: event_logs.source, event_logs.action"))
    assert database_error_payload(error)["code"] == "DATABASE_CONSTRAINT_ERROR"
    record_engine_error(tmp_path, error)
    log = (tmp_path / "engine-errors.jsonl").read_text()
    assert "private SQL" not in log and "synthetic secret" not in log
    assert json.loads(log)["constraint_columns"] == ["event_logs.source", "event_logs.action"]


def test_doctor_probe_detects_full_disk_not_just_empty_file_creation(tmp_path, monkeypatch):
    from studyflow.infrastructure import health
    def fail_flush(fd):
        raise OSError(28, "synthetic full disk")
    monkeypatch.setattr(health.os, "fsync", fail_flush)
    result = health.write_probe(tmp_path)
    assert result["writable"] is False
    assert result["reason"] == "disk_full" and result["phase"] == "write"
    assert not list(tmp_path.glob(".studyflow-write-check-*"))

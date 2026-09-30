from __future__ import annotations

import sqlite3

from studyflow.config import Settings
from studyflow.db import build_engine, init_db
from studyflow.migrations import upgrade_sqlite
from studyflow.models import PlanLine


def test_existing_legacy_sqlite_gets_additive_columns_without_losing_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    engine = build_engine(settings)
    init_db(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO plan_lines (id, name, priority, status) VALUES ('p1', 'Legacy Plan', 1, 'ACTIVE')")
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        connection.exec_driver_sql("ALTER TABLE tasks DROP COLUMN task_kind") if False else None
    # Construct a true old-schema copy for the three changed tables.
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE legacy_tasks AS SELECT id, stage_id, title, description, scheduled_date, status, reason, next_action, priority, created_at, updated_at FROM tasks")
    connection.execute("DROP TABLE tasks")
    connection.execute("ALTER TABLE legacy_tasks RENAME TO tasks")
    connection.execute("CREATE TABLE legacy_courses AS SELECT id, plan_line_id, title, summary, version, status, created_at, updated_at FROM courses")
    connection.execute("DROP TABLE courses")
    connection.execute("ALTER TABLE legacy_courses RENAME TO courses")
    connection.execute("CREATE TABLE legacy_exercises AS SELECT id, lesson_id, title, prompt, requirements, position, created_at, updated_at FROM exercises")
    connection.execute("DROP TABLE exercises")
    connection.execute("ALTER TABLE legacy_exercises RENAME TO exercises")
    connection.commit()
    connection.close()

    result = upgrade_sqlite(settings)
    assert result["upgraded"] is True
    assert result["backup"]
    backup = sqlite3.connect(result["backup"])
    assert backup.execute("SELECT name FROM plan_lines WHERE id='p1'").fetchone()[0] == "Legacy Plan"
    backup.close()
    check = sqlite3.connect(db_path)
    assert check.execute("SELECT name FROM plan_lines WHERE id='p1'").fetchone()[0] == "Legacy Plan"
    assert "task_kind" in {row[1] for row in check.execute("PRAGMA table_info(tasks)")}
    assert "subject" in {row[1] for row in check.execute("PRAGMA table_info(courses)")}
    check.close()


def test_empty_database_runs_checked_in_alembic_chain(tmp_path):
    db_path = tmp_path / "empty.db"
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    result = upgrade_sqlite(settings)
    assert result["status"] == "FRESH_DATABASE_MIGRATED"
    check = sqlite3.connect(db_path)
    tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"plan_lines", "tasks", "courses", "exercises", "alembic_version", "course_write_receipts"}.issubset(tables)
    assert check.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005_course_answers"
    assert "task_kind" in {row[1] for row in check.execute("PRAGMA table_info(tasks)")}
    assert "content_type" in {row[1] for row in check.execute("PRAGMA table_info(courses)")}
    assert "exercise_type" in {row[1] for row in check.execute("PRAGMA table_info(exercises)")}
    check.close()


def test_partial_schema_fails_closed(tmp_path):
    db_path = tmp_path / "partial.db"
    sqlite3.connect(db_path).execute("CREATE TABLE tasks (id VARCHAR(36))")
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    from studyflow.domain import DomainError
    try:
        upgrade_sqlite(settings)
    except DomainError as exc:
        assert exc.code == "PARTIAL_SCHEMA_UNSUPPORTED"
    else:
        raise AssertionError("expected partial schema failure")



def test_current_legacy_database_gets_version_stamp_without_data_loss(tmp_path):
    db_path = tmp_path / "current.db"
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    engine = build_engine(settings)
    init_db(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO plan_lines (id, name, priority, status) VALUES ('p1', 'Current Plan', 1, 'ACTIVE')")
        connection.exec_driver_sql("DROP TABLE learning_progress")
    result = upgrade_sqlite(settings)
    assert result["status"] == "LEGACY_STAMPED_UPGRADED"
    check = sqlite3.connect(db_path)
    assert check.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005_course_answers"
    assert check.execute("SELECT name FROM plan_lines WHERE id='p1'").fetchone()[0] == "Current Plan"
    assert "learning_progress" in {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check.close()


def test_empty_alembic_version_table_is_stamped_without_rebuilding(tmp_path):
    db_path = tmp_path / "unstamped.db"
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    engine = build_engine(settings)
    init_db(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO plan_lines (id, name, priority, status) VALUES ('p1', 'Unstamped Plan', 1, 'ACTIVE')")
        connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
    result = upgrade_sqlite(settings)
    assert result["status"] == "LEGACY_STAMPED_UPGRADED"
    check = sqlite3.connect(db_path)
    assert check.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005_course_answers"
    assert check.execute("SELECT name FROM plan_lines WHERE id='p1'").fetchone()[0] == "Unstamped Plan"
    check.close()



def test_current_revision_missing_progress_table_fails_closed(tmp_path):
    db_path = tmp_path / "broken-current.db"
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    engine = build_engine(settings)
    init_db(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE learning_progress")
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('0004_learning_progress')")
    from studyflow.domain import DomainError
    try:
        upgrade_sqlite(settings)
    except DomainError as exc:
        assert exc.code == "SCHEMA_REVISION_MISMATCH"
    else:
        raise AssertionError("expected a fail-closed schema mismatch")

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from studyflow.infrastructure.config import Settings


from studyflow.infrastructure.persistence.base import Base


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Keep SQLite transient B-trees in memory for long local write transactions.

    On Windows, the default file-backed temp store can fail to open during a
    long ORM ``RETURNING`` transaction even though the main database is writable.
    This is a per-connection SQLite setting and does not affect MySQL.
    """
    dbapi_connection.execute("PRAGMA temp_store=MEMORY")


def _configure_sqlite_engine(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    if not getattr(engine, "_studyflow_sqlite_temp_store_configured", False):
        event.listen(engine, "connect", _configure_sqlite_connection)
        setattr(engine, "_studyflow_sqlite_temp_store_configured", True)
    # ``init_db`` may receive an engine created by a caller rather than
    # ``build_engine``. Apply the pragma to the current pooled connection too.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA temp_store=MEMORY")


def build_engine(settings: Settings) -> Engine:
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
    _configure_sqlite_engine(engine)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    _configure_sqlite_engine(engine)
    from studyflow.infrastructure.persistence import registry as models  # noqa: F401

    # Recognized file-backed SQLite upgrades take a consistent backup before 0006 adds evidence links.
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        with engine.connect() as connection:
            revision=connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        from studyflow.infrastructure.persistence.migrations import CURRENT_REVISION
        if revision and revision.split("_")[0].isdigit() and int(revision.split("_")[0])>int(CURRENT_REVISION.split("_")[0]):
            from studyflow.shared.domain import DomainError
            raise DomainError("NEWER_SCHEMA_UNSUPPORTED","该工作区由更新版本创建，未写入任何内容。","使用匹配的新版本CLI/应用。")
    if engine.dialect.name == "sqlite" and engine.url.database not in {None, ":memory:"} and "submissions" in tables:
        from pathlib import Path
        from studyflow.infrastructure.persistence.migrations import LEGACY_TABLES, upgrade_sqlite
        columns = {column["name"] for column in inspector.get_columns("submissions")}
        needs_study = "course_study_sessions" not in tables or not {"study_session_id","batch_id"}.issubset(columns)
        event_signature = {"source", "object_type", "object_id", "action", "summary"}
        bad_event_constraint = "event_logs" in tables and any(set(row["column_names"]) == event_signature for row in inspector.get_unique_constraints("event_logs"))
        needs_tools = not {"study_notes", "study_note_receipts"}.issubset(tables)
        needs_plans = "plan_write_receipts" not in tables
        needs_revisions = "course_revisions" not in tables
        needs_reviews = "retest_tasks" not in tables or "retest_task_id" not in {c["name"] for c in inspector.get_columns("submissions")}
        needs_contract = "submission_chain_links" not in tables or "payload_hash" not in {c["name"] for c in inspector.get_columns("submission_write_receipts")} if "submission_write_receipts" in tables else True
        if (needs_plans or needs_revisions or needs_reviews or needs_contract or needs_study or bad_event_constraint or needs_tools) and LEGACY_TABLES.issubset(tables):
            database_path = Path(engine.url.database).resolve()
            upgrade_sqlite(Settings(workspace_root=database_path.parent, database_url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(engine)
    ensure_compatible_schema(engine)


def ensure_compatible_schema(engine: Engine) -> None:
    """Apply additive compatibility changes for a running local database."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "tasks" not in tables or "courses" not in tables or "exercises" not in tables:
        return
    statements: list[str] = []
    table_columns = {table: {column["name"] for column in inspector.get_columns(table)} for table in tables}
    additions = {
        "plan_lines": {"version": "INTEGER NOT NULL DEFAULT 1", "focus_course_id": "VARCHAR(36)"},
        "tasks": {
            "plan_line_id": "VARCHAR(36)",
            "task_kind": "VARCHAR(40) NOT NULL DEFAULT 'OTHER'",
            "course_schedule_item_id": "VARCHAR(36)",
        },
        "courses": {
            "subject": "VARCHAR(120) NOT NULL DEFAULT ''",
            "content_type": "VARCHAR(40) NOT NULL DEFAULT 'LESSON'",
            "difficulty": "VARCHAR(32) NOT NULL DEFAULT ''",
            "source_type": "VARCHAR(32) NOT NULL DEFAULT 'AGENT_CLI'",
        },
        "lessons": {"semantic_id": "VARCHAR(120) NOT NULL DEFAULT ''", "included": "BOOLEAN NOT NULL DEFAULT 1"},
        "exercises": {"semantic_id": "VARCHAR(120) NOT NULL DEFAULT ''", "included": "BOOLEAN NOT NULL DEFAULT 1", "exercise_type": "VARCHAR(40) NOT NULL DEFAULT 'SHORT_ANSWER'"},
        "submissions": {
            "parent_submission_id": "VARCHAR(36)",
            "attempt_number": "INTEGER NOT NULL DEFAULT 1",
            "attempt_kind": "VARCHAR(24) NOT NULL DEFAULT 'FIRST'",
            "next_action": "TEXT NOT NULL DEFAULT ''",
            "study_session_id": "VARCHAR(36)",
            "batch_id": "VARCHAR(36)",
            "retest_task_id": "VARCHAR(36)",
        },
        "submission_write_receipts": {"payload_hash": "VARCHAR(64)", "result_json": "TEXT"},
        "course_write_receipts": {"study_session_id": "VARCHAR(36)"},
        "review_feedback": {
            "issues_json": "TEXT NOT NULL DEFAULT '[]'",
            "decision": "VARCHAR(32) NOT NULL DEFAULT 'PASSED'",
            "next_action": "TEXT NOT NULL DEFAULT ''",
        },
    }
    for table, columns in additions.items():
        if table not in tables:
            continue
        for name, definition in columns.items():
            if name not in table_columns[table]:
                statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            if "plan_line_id" not in table_columns["tasks"] and "stages" in tables:
                connection.execute(text("UPDATE tasks SET plan_line_id = (SELECT stages.plan_line_id FROM stages WHERE stages.id = tasks.stage_id) WHERE plan_line_id IS NULL"))
    # create_all() can create the new relationship tables without adding any
    # columns, so backfill must run even when no ALTER TABLE was necessary.
    with engine.begin() as connection:
        _backfill_plan_course_items(connection, tables)


def _backfill_plan_course_items(connection, tables: list[str] | set[str]) -> None:
    """Link legacy courses into the ordered-course model after create_all()."""
    required = {"courses", "plan_course_items"}
    if not required.issubset(set(tables)):
        return
    rows = connection.execute(text("SELECT id, plan_line_id FROM courses WHERE plan_line_id IS NOT NULL ORDER BY created_at, id")).fetchall()
    next_sequence: dict[str, int] = {}
    for course_id, plan_line_id in rows:
        exists = connection.execute(
            text("SELECT 1 FROM plan_course_items WHERE plan_line_id = :plan_line_id AND course_id = :course_id"),
            {"plan_line_id": plan_line_id, "course_id": course_id},
        ).first()
        if exists:
            continue
        if plan_line_id not in next_sequence:
            next_sequence[plan_line_id] = int(connection.execute(text("SELECT COALESCE(MAX(sequence_number), 0) FROM plan_course_items WHERE plan_line_id = :plan_line_id"), {"plan_line_id": plan_line_id}).scalar_one())
        next_sequence[plan_line_id] += 1
        connection.execute(
            text("INSERT INTO plan_course_items (id, plan_line_id, course_id, sequence_number, status) VALUES (:id, :plan_line_id, :course_id, :sequence_number, 'PLANNED')"),
            {"id": str(__import__('uuid').uuid4()), "plan_line_id": plan_line_id, "course_id": course_id, "sequence_number": next_sequence[plan_line_id]},
        )


def get_session(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
    finally:
        session.close()

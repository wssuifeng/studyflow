from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from studyflow.infrastructure.config import Settings


from studyflow.infrastructure.persistence.base import Base


def build_engine(settings: Settings) -> Engine:
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    from studyflow.infrastructure.persistence import registry as models  # noqa: F401

    # Recognized file-backed SQLite upgrades take a consistent backup before 0006 adds evidence links.
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if engine.dialect.name == "sqlite" and engine.url.database not in {None, ":memory:"} and "submissions" in tables:
        from pathlib import Path
        from studyflow.infrastructure.persistence.migrations import LEGACY_TABLES, upgrade_sqlite
        columns = {column["name"] for column in inspector.get_columns("submissions")}
        needs_study = "course_study_sessions" not in tables or not {"study_session_id","batch_id"}.issubset(columns)
        if needs_study and LEGACY_TABLES.issubset(tables):
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
        "exercises": {"exercise_type": "VARCHAR(40) NOT NULL DEFAULT 'SHORT_ANSWER'"},
        "submissions": {
            "parent_submission_id": "VARCHAR(36)",
            "attempt_number": "INTEGER NOT NULL DEFAULT 1",
            "attempt_kind": "VARCHAR(24) NOT NULL DEFAULT 'FIRST'",
            "next_action": "TEXT NOT NULL DEFAULT ''",
            "study_session_id": "VARCHAR(36)",
            "batch_id": "VARCHAR(36)",
        },
        "course_write_receipts": {"study_session_id": "VARCHAR(36)"},
        "review_feedback": {
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

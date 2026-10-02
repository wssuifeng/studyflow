"""Add generic learning metadata to the MVP schema.

Revision ID: 0002_generic_metadata
Revises: 0001_mvp_baseline
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_generic_metadata"
down_revision = "0001_mvp_baseline"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _add(table: str, name: str, definition: str) -> None:
    if not _columns(table):
        return
    if name not in _columns(table):
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def upgrade() -> None:
    _add("tasks", "plan_line_id", "VARCHAR(36)")
    _add("tasks", "task_kind", "VARCHAR(40) NOT NULL DEFAULT 'OTHER'")
    _add("courses", "subject", "VARCHAR(120) NOT NULL DEFAULT ''")
    _add("courses", "content_type", "VARCHAR(40) NOT NULL DEFAULT 'LESSON'")
    _add("courses", "difficulty", "VARCHAR(32) NOT NULL DEFAULT ''")
    _add("courses", "source_type", "VARCHAR(32) NOT NULL DEFAULT 'CODEX'")
    _add("exercises", "exercise_type", "VARCHAR(40) NOT NULL DEFAULT 'SHORT_ANSWER'")


def downgrade() -> None:
    # SQLite cannot safely drop columns across supported versions; rollback is
    # intentionally performed by restoring the backup created before upgrade.
    raise RuntimeError("Restore the pre-upgrade backup instead of dropping generic metadata columns.")

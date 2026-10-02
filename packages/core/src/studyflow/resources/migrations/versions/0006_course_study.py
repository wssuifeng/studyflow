"""Freeze local course study rounds without rewriting existing learning evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0006_course_study"
down_revision = "0005_course_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "course_study_sessions" not in tables:
        op.create_table("course_study_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
            sa.Column("new_version", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("progress_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("resume_lesson_id", sa.String(36), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("reading_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("course_id", "revision", name="uq_course_study_revision"))
        op.create_index("ix_course_study_sessions_course_id", "course_study_sessions", ["course_id"])
    for table, fields in {"submissions": ["study_session_id", "batch_id"], "course_write_receipts": ["study_session_id"]}.items():
        columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}
        for field in fields:
            if field not in columns:
                op.add_column(table, sa.Column(field, sa.String(36), nullable=True))
                op.create_index(f"ix_{table}_{field}", table, [field])


def downgrade() -> None:
    raise RuntimeError("Study snapshots preserve original questions; restore a verified backup instead.")

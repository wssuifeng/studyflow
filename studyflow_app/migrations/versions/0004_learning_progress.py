"""Persist per-lesson reading progress separately from demonstrated mastery."""

from alembic import op
import sqlalchemy as sa

revision = "0004_learning_progress"
down_revision = "0003_learning_console_lifecycle"
branch_labels = None
depends_on = None


def _create_learning_progress() -> None:
    bind = op.get_bind()
    if "learning_progress" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "learning_progress",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="NOT_STARTED"),
        sa.Column("last_position", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="USER_ENGINE"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "lesson_id", name="uq_learning_progress_course_lesson"),
    )
    op.create_index("ix_learning_progress_course_id", "learning_progress", ["course_id"])
    op.create_index("ix_learning_progress_lesson_id", "learning_progress", ["lesson_id"])
    op.create_index("ix_learning_progress_status", "learning_progress", ["status"])


def upgrade() -> None:
    _create_learning_progress()
    if "submission_write_receipts" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "submission_write_receipts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
            sa.Column("operation", sa.String(40), nullable=False),
            sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_submission_write_receipts_submission_id", "submission_write_receipts", ["submission_id"])


def downgrade() -> None:
    raise RuntimeError("Learning progress is user data; restore a pre-upgrade backup instead of dropping it.")

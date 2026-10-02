"""Create the pre-generalization StudyFlow MVP schema.

Revision ID: 0001_mvp_baseline
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_mvp_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if existing <= {"alembic_version"}:
        op.create_table(
            "plan_lines",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False, unique=True),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "stages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("plan_line_id", sa.String(36), sa.ForeignKey("plan_lines.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("window_start", sa.Date(), nullable=False),
            sa.Column("window_end", sa.Date(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("stage_id", sa.String(36), sa.ForeignKey("stages.id"), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("scheduled_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="TODO"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "time_blocks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False),
            sa.Column("block_date", sa.Date(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.Column("actual_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "courses",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("plan_line_id", sa.String(36), sa.ForeignKey("plan_lines.id"), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "lessons",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("markdown_path", sa.String(500), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "exercises",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("requirements", sa.Text(), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "submissions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("exercise_id", sa.String(36), sa.ForeignKey("exercises.id"), nullable=False),
            sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True),
            sa.Column("answer_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("source", sa.String(32), nullable=False, server_default="USER_WEB"),
            sa.Column("idempotency_key", sa.String(160), nullable=True, unique=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "review_feedback",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id"), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("detail_markdown", sa.Text(), nullable=False, server_default=""),
            sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("needs_revision", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(32), nullable=False, server_default="CODEX_CLI"),
            sa.Column("idempotency_key", sa.String(160), nullable=True, unique=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("relative_path", sa.String(500), nullable=False, unique=True),
            sa.Column("document_type", sa.String(40), nullable=False, server_default="MARKDOWN"),
            sa.Column("status", sa.String(24), nullable=False, server_default="PRESENT"),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("modified_at", sa.DateTime(), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "context_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("scope", sa.String(32), nullable=False, server_default="today"),
            sa.Column("relative_path", sa.String(500), nullable=False),
            sa.Column("current_pointer", sa.Text(), nullable=False, server_default=""),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_table(
            "event_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("object_type", sa.String(40), nullable=False),
            sa.Column("object_id", sa.String(36), nullable=False),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("source", "object_type", "object_id", "action", "summary", name="uq_event_signature"),
        )
    for table, columns in {
        "stages": ["plan_line_id"], "tasks": ["stage_id", "scheduled_date", "status"],
        "time_blocks": ["task_id"], "courses": ["plan_line_id"], "lessons": ["course_id"],
        "exercises": ["lesson_id", "exercise_type"], "submissions": ["exercise_id", "task_id", "status"],
        "review_feedback": ["submission_id"], "documents": ["status"], "context_snapshots": ["snapshot_date"],
    }.items():
        for column in columns:
            index_name = f"ix_{table}_{column}"
            try:
                op.create_index(index_name, table, [column])
            except Exception:
                pass


def downgrade() -> None:
    for table in ["event_logs", "context_snapshots", "documents", "review_feedback", "submissions", "exercises", "lessons", "courses", "time_blocks", "tasks", "stages", "plan_lines"]:
        op.drop_table(table)

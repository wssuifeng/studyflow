"""Append-only events and per-frozen-lesson personal scratch notes."""
from alembic import op
import sqlalchemy as sa

revision = "0007_learning_tools"
down_revision = "0006_course_study"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    signature = {"source", "object_type", "object_id", "action", "summary"}
    matches = [row for row in inspector.get_unique_constraints("event_logs") if set(row["column_names"]) == signature]
    if matches:
        # SQLite needs a table rebuild; batch preserves all event rows and indexes.
        with op.batch_alter_table("event_logs", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
            for row in matches:
                batch.drop_constraint(row["name"] or "uq_event_logs_source", type_="unique")
    tables = set(sa.inspect(bind).get_table_names())
    if "study_notes" not in tables:
        op.create_table(
            "study_notes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("study_session_id", sa.String(36), sa.ForeignKey("course_study_sessions.id"), nullable=False),
            sa.Column("lesson_id", sa.String(36), nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            *_timestamps(), sa.UniqueConstraint("study_session_id", "lesson_id", name="uq_study_note_lesson"),
        )
        op.create_index("ix_study_notes_study_session_id", "study_notes", ["study_session_id"])
    if "study_note_receipts" not in tables:
        op.create_table(
            "study_note_receipts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
            sa.Column("study_session_id", sa.String(36), sa.ForeignKey("course_study_sessions.id"), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False), *_timestamps(),
        )
        op.create_index("ix_study_note_receipts_study_session_id", "study_note_receipts", ["study_session_id"])


def downgrade():
    # Reintroducing the signature constraint can lose repeated legitimate events.
    raise RuntimeError("Restore the consistency backup instead of deleting notes or repeated event history.")

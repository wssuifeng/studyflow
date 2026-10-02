"""Add durable, payload-bound receipts for atomic whole-course answer writes."""
from alembic import op
import sqlalchemy as sa

revision = "0005_course_answers"
down_revision = "0004_learning_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "course_write_receipts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "course_write_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_course_write_receipts_course_id", "course_write_receipts", ["course_id"])


def downgrade() -> None:
    raise RuntimeError("Course write receipts protect learning data; restore a pre-upgrade backup instead.")

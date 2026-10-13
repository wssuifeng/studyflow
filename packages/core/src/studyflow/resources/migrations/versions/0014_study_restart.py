"""Preserve explicitly abandoned reading rounds; no historical content is deleted."""
from alembic import op
import sqlalchemy as sa
revision = "0014_study_restart"
down_revision = "0013_english_specialty"
branch_labels = None
depends_on = None

def upgrade():
    if "abandoned_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("course_study_sessions")}:
        op.add_column("course_study_sessions", sa.Column("abandoned_at", sa.DateTime(), nullable=True))

def downgrade():
    raise RuntimeError("学习轮次历史不可自动丢弃；请恢复经验证的一致性备份。")

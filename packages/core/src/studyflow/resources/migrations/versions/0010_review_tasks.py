"""Structured feedback and immutable retest tasks."""
from alembic import op
import sqlalchemy as sa
revision="0010_review_tasks"
down_revision="0009_write_contract"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    from studyflow.modules.reviews.models import RetestTask
    RetestTask.__table__.create(bind,checkfirst=True)
    for table,column in [("submissions",sa.Column("retest_task_id",sa.String(36),nullable=True)),("review_feedback",sa.Column("issues_json",sa.Text(),server_default="[]",nullable=False))]:
        if column.name not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:op.add_column(table,column)

def downgrade():
    raise RuntimeError("复测与反馈包含学习证据，不自动降级。")

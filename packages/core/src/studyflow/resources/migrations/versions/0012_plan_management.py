"""Versioned plan and schedule edits, no deletion of learning records."""
from alembic import op
import sqlalchemy as sa
revision="0012_plan_management"
down_revision="0011_course_revisions"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    from studyflow.modules.planning.models import PlanWriteReceipt
    PlanWriteReceipt.__table__.create(bind,checkfirst=True)
    columns={c["name"] for c in sa.inspect(bind).get_columns("plan_lines")}
    if "version" not in columns:op.add_column("plan_lines",sa.Column("version",sa.Integer(),server_default="1",nullable=False))
    if "focus_course_id" not in columns:op.add_column("plan_lines",sa.Column("focus_course_id",sa.String(36),nullable=True))

def downgrade():raise RuntimeError("计划历史含用户安排，不自动降级。")

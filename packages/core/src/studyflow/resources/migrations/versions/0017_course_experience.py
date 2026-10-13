"""Add local reference view evidence and membership management without rewriting history."""
from alembic import op
import sqlalchemy as sa
revision="0017_course_experience"
down_revision="0016_notebook_document"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    additions={"course_study_sessions":[sa.Column("hint_tracking_enabled",sa.Boolean(),nullable=False,server_default="0")],"plan_course_items":[sa.Column("management_position",sa.String(20),nullable=False,server_default="NORMAL"),sa.Column("management_reason",sa.Text(),nullable=False,server_default="")],"review_feedback":[sa.Column("reference_hash",sa.String(64),nullable=True),sa.Column("reference_revision",sa.Integer(),nullable=True),sa.Column("reference_reason",sa.Text(),nullable=False,server_default="")]}
    for table,columns in additions.items():
        existing={c["name"] for c in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:op.add_column(table,column)
    from studyflow.modules.learning.models import CourseReferenceView
    CourseReferenceView.__table__.create(bind,checkfirst=True)

def downgrade():
    raise RuntimeError("不自动删除课程状态或提示证据；恢复经过验证的备份。")

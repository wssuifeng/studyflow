"""Retain identity and obsolete entities across course publications."""
from alembic import op
import sqlalchemy as sa
revision="0011_course_revisions"
down_revision="0010_review_tasks"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    from studyflow.modules.courses.models import CourseRevision
    CourseRevision.__table__.create(bind,checkfirst=True)
    for table in ("lessons","exercises"):
        columns={c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "semantic_id" not in columns:op.add_column(table,sa.Column("semantic_id",sa.String(120),server_default="",nullable=False))
        if "included" not in columns:op.add_column(table,sa.Column("included",sa.Boolean(),server_default=sa.true(),nullable=False))

def downgrade():raise RuntimeError("保留旧版课程和答案，不自动降级。")

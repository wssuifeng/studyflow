"""Add supplemental course provenance without changing historical learning evidence."""
from alembic import op
import sqlalchemy as sa
revision="0015_english_remediation"
down_revision="0014_study_restart"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    if "track" not in {c["name"] for c in sa.inspect(bind).get_columns("plan_course_items")}:
        op.add_column("plan_course_items",sa.Column("track",sa.String(20),nullable=False,server_default="MAIN"))
    from studyflow.modules.mistakes.remediation.models import EnglishRemediationCourse, EnglishRemediationSource
    EnglishRemediationCourse.__table__.create(bind,checkfirst=True)
    EnglishRemediationSource.__table__.create(bind,checkfirst=True)

def downgrade():
    raise RuntimeError("补充课程来源和学习记录不可自动丢弃；恢复经验证的一致性备份。")

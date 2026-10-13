"""Add controlled notebook documents without discarding legacy blocks."""
from alembic import op
import sqlalchemy as sa
revision = "0016_notebook_document"
down_revision = "0015_english_remediation"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("plan_notebooks")}
    if "format_version" not in columns:
        op.add_column("plan_notebooks", sa.Column("format_version", sa.Integer(), nullable=False, server_default="1"))
    if "document_json" not in columns:
        op.add_column("plan_notebooks", sa.Column("document_json", sa.Text(), nullable=False, server_default='{"entries":[]}'))
    from studyflow.modules.learning.models import PlanNotebookSource
    PlanNotebookSource.__table__.create(bind, checkfirst=True)


def downgrade():
    raise RuntimeError("笔记结构与出处不可自动丢弃；恢复经过验证的一致性备份。")

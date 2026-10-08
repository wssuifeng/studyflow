"""Add continuous plan notebooks; preserve legacy study notes and all answers."""
from alembic import op
import sqlalchemy as sa
revision="0008_plan_notebooks"
down_revision="0007_learning_tools"
branch_labels=None
depends_on=None

def upgrade():
    from studyflow.modules.learning.models import PlanNotebook, PlanNotebookReceipt
    for table in (PlanNotebook.__table__, PlanNotebookReceipt.__table__):
        table.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError("笔记降级可能丢失私人内容，需显式备份和恢复，不自动删表。")

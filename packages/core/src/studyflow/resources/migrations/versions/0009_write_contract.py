"""Add chain claims and verified receipts; preserve legacy hashes as NULL."""
from alembic import op
import sqlalchemy as sa
revision="0009_write_contract"
down_revision="0008_plan_notebooks"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    columns={c["name"] for c in sa.inspect(bind).get_columns("submission_write_receipts")}
    for name,kind in [("payload_hash",sa.String(64)),("result_json",sa.Text())]:
        if name not in columns: op.add_column("submission_write_receipts",sa.Column(name,kind,nullable=True))
    from studyflow.modules.learning.models import SubmissionChainLink
    SubmissionChainLink.__table__.create(bind,checkfirst=True)

def downgrade():
    raise RuntimeError("版本链包含用户审计记录，降级需备份恢复。")

"""Add continuous plan notebooks; preserve legacy study notes and all answers."""
from alembic import op
import sqlalchemy as sa
revision="0008_plan_notebooks"
down_revision="0007_learning_tools"
branch_labels=None
depends_on=None

def upgrade():
    # Freeze historical DDL here. Importing today's ORM leaked future document
    # columns into a database explicitly upgraded only to 0008/0015.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    def timestamps():
        return [sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),
                sa.Column("updated_at",sa.DateTime(),nullable=False,server_default=sa.func.now())]
    if "plan_notebooks" not in tables:
        op.create_table("plan_notebooks",sa.Column("id",sa.String(36),primary_key=True),
            sa.Column("plan_line_id",sa.String(36),sa.ForeignKey("plan_lines.id"),nullable=False,unique=True),
            sa.Column("blocks_json",sa.Text(),nullable=False,server_default="[]"),
            sa.Column("version",sa.Integer(),nullable=False,server_default="1"),*timestamps())
    if "plan_notebook_receipts" not in tables:
        op.create_table("plan_notebook_receipts",sa.Column("id",sa.String(36),primary_key=True),
            sa.Column("idempotency_key",sa.String(160),nullable=False,unique=True),
            sa.Column("plan_line_id",sa.String(36),sa.ForeignKey("plan_lines.id"),nullable=False),
            sa.Column("payload_hash",sa.String(64),nullable=False),sa.Column("result_json",sa.Text(),nullable=False),*timestamps())
        op.create_index("ix_plan_notebook_receipts_plan_line_id","plan_notebook_receipts",["plan_line_id"])

def downgrade():
    raise RuntimeError("笔记降级可能丢失私人内容，需显式备份和恢复，不自动删表。")

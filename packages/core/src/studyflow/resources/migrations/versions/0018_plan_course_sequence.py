"""Enforce stable course numbers within each plan track."""
from alembic import op
import sqlalchemy as sa

revision = "0018_plan_course_sequence"
down_revision = "0017_course_experience"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, plan_line_id, track, sequence_number "
        "FROM plan_course_items ORDER BY plan_line_id, track, sequence_number, id"
    )).mappings().all()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["plan_line_id"], row["track"] or "MAIN"), []).append(row)

    # Normalize every track to a contiguous stable sequence. Temporary negative
    # values avoid collisions even when a legacy database already has duplicates.
    for group in grouped.values():
        for index, row in enumerate(group, 1):
            bind.execute(
                sa.text("UPDATE plan_course_items SET sequence_number=:sequence WHERE id=:id"),
                {"sequence": -index, "id": row["id"]},
            )
    for group in grouped.values():
        for index, row in enumerate(group, 1):
            bind.execute(
                sa.text("UPDATE plan_course_items SET sequence_number=:sequence WHERE id=:id"),
                {"sequence": index, "id": row["id"]},
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("plan_course_items")}
    if "uq_plan_course_item_position" not in indexes:
        op.create_index(
            "uq_plan_course_item_position",
            "plan_course_items",
            ["plan_line_id", "track", "sequence_number"],
            unique=True,
        )


def downgrade():
    raise RuntimeError("课程序号约束用于保护学习导航，不自动删除；恢复经验证的一致性备份。")

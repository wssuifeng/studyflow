"""Add ordered plan courses, daily course windows, and submission lifecycle links."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0003_learning_console_lifecycle"
down_revision = "0002_generic_metadata"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if table in sa.inspect(op.get_bind()).get_table_names() and column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "plan_course_items" not in tables:
        op.create_table(
            "plan_course_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("plan_line_id", sa.String(36), sa.ForeignKey("plan_lines.id"), nullable=False),
            sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(24), nullable=False, server_default="PLANNED"),
            sa.Column("planned_start", sa.Date(), nullable=True),
            sa.Column("planned_end", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("plan_line_id", "course_id", name="uq_plan_course_item_course"),
        )
        op.create_index("ix_plan_course_items_plan_line_id", "plan_course_items", ["plan_line_id"])
        op.create_index("ix_plan_course_items_course_id", "plan_course_items", ["course_id"])

    if "course_schedule_items" not in tables:
        op.create_table(
            "course_schedule_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("plan_course_item_id", sa.String(36), sa.ForeignKey("plan_course_items.id"), nullable=False),
            sa.Column("scheduled_date", sa.Date(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("start_time", sa.Time(), nullable=True),
            sa.Column("end_time", sa.Time(), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="PLANNED"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("plan_course_item_id", "scheduled_date", name="uq_course_schedule_day"),
        )
        op.create_index("ix_course_schedule_items_plan_course_item_id", "course_schedule_items", ["plan_course_item_id"])
        op.create_index("ix_course_schedule_items_scheduled_date", "course_schedule_items", ["scheduled_date"])

    _add_column("tasks", sa.Column("course_schedule_item_id", sa.String(36), nullable=True))
    _add_column("submissions", sa.Column("parent_submission_id", sa.String(36), nullable=True))
    _add_column("submissions", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    _add_column("submissions", sa.Column("attempt_kind", sa.String(24), nullable=False, server_default="FIRST"))
    _add_column("submissions", sa.Column("next_action", sa.Text(), nullable=False, server_default=""))
    _add_column("review_feedback", sa.Column("decision", sa.String(32), nullable=False, server_default="PASSED"))
    _add_column("review_feedback", sa.Column("next_action", sa.Text(), nullable=False, server_default=""))

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("tasks")} if "tasks" in inspector.get_table_names() else set()
    if "ix_tasks_course_schedule_item_id" not in existing_indexes and "tasks" in inspector.get_table_names():
        op.create_index("ix_tasks_course_schedule_item_id", "tasks", ["course_schedule_item_id"])
    existing_indexes = {index["name"] for index in inspector.get_indexes("submissions")} if "submissions" in inspector.get_table_names() else set()
    if "ix_submissions_parent_submission_id" not in existing_indexes and "submissions" in inspector.get_table_names():
        op.create_index("ix_submissions_parent_submission_id", "submissions", ["parent_submission_id"])

    if "plan_course_items" in sa.inspect(bind).get_table_names() and "courses" in sa.inspect(bind).get_table_names():
        courses = sa.table("courses", sa.column("id", sa.String), sa.column("plan_line_id", sa.String), sa.column("created_at", sa.DateTime))
        items = sa.table("plan_course_items", sa.column("id", sa.String), sa.column("plan_line_id", sa.String), sa.column("course_id", sa.String), sa.column("sequence_number", sa.Integer), sa.column("status", sa.String))
        rows = bind.execute(sa.select(courses.c.id, courses.c.plan_line_id).where(courses.c.plan_line_id.is_not(None)).order_by(courses.c.created_at, courses.c.id)).fetchall()
        next_sequence: dict[str, int] = {}
        for course_id, plan_line_id in rows:
            exists = bind.execute(sa.select(items.c.id).where(items.c.plan_line_id == plan_line_id, items.c.course_id == course_id)).first()
            if exists:
                continue
            next_sequence[plan_line_id] = next_sequence.get(plan_line_id, 0) + 1
            bind.execute(sa.insert(items).values(id=str(uuid4()), plan_line_id=plan_line_id, course_id=course_id, sequence_number=next_sequence[plan_line_id], status="PLANNED"))


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup instead of dropping learning console lifecycle columns and tables.")

"""Add English training and plan/course-scoped error domains; historical tables stay intact."""
from alembic import op
import sqlalchemy as sa

revision = "0013_english_specialty"
down_revision = "0012_plan_management"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, column, definition in [("courses", "learning_mode", sa.Column("learning_mode", sa.String(20), nullable=False, server_default="general")), ("retest_tasks", "task_mode", sa.Column("task_mode", sa.String(20), nullable=False, server_default="general")), ("retest_tasks", "payload_json", sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"))]:
        if column not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table, definition)
    if 'english_items' not in tables:
        op.create_table('english_items',
            sa.Column('exercise_id', sa.String(36), sa.ForeignKey('exercises.id'), primary_key=True, nullable=False),
            sa.Column('spec_json', sa.Text(), nullable=False),
        )
    if 'english_study_states' not in tables:
        op.create_table('english_study_states',
            sa.Column('study_session_id', sa.String(36), sa.ForeignKey('course_study_sessions.id'), primary_key=True, nullable=False),
            sa.Column('plan_line_id', sa.String(36), sa.ForeignKey('plan_lines.id'), nullable=True),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('completed', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if 'english_check_attempts' not in tables:
        op.create_table('english_check_attempts',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('study_session_id', sa.String(36), sa.ForeignKey('course_study_sessions.id'), nullable=False),
            sa.Column('exercise_id', sa.String(36), sa.ForeignKey('exercises.id'), nullable=False),
            sa.Column('submission_id', sa.String(36), sa.ForeignKey('submissions.id'), nullable=False),
            sa.Column('retest_task_id', sa.String(36), sa.ForeignKey('retest_tasks.id'), nullable=True),
            sa.Column('answer_text', sa.Text(), nullable=False),
            sa.Column('answer_version', sa.Integer(), nullable=False),
            sa.Column('rule_hash', sa.String(64), nullable=False),
            sa.Column('result_json', sa.Text(), nullable=False),
            sa.Column('assisted', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_en_check_scope', 'english_check_attempts', ['study_session_id', 'exercise_id', 'created_at', 'id'], unique=False)
    if 'english_submission_details' not in tables:
        op.create_table('english_submission_details',
            sa.Column('submission_id', sa.String(36), sa.ForeignKey('submissions.id'), primary_key=True, nullable=False),
            sa.Column('last_attempt_id', sa.String(36), sa.ForeignKey('english_check_attempts.id'), nullable=True),
            sa.Column('assisted', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('skipped', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('evaluation_mode', sa.String(20), nullable=False, server_default='local_exact'),
        )
    if 'mistake_notebooks' not in tables:
        op.create_table('mistake_notebooks',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('scope_key', sa.String(80), nullable=False),
            sa.Column('plan_line_id', sa.String(36), sa.ForeignKey('plan_lines.id'), nullable=True),
            sa.Column('domain', sa.String(20), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('scope_key', 'domain', name='uq_mistake_scope'),
        )
    if 'english_error_aggregates' not in tables:
        op.create_table('english_error_aggregates',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('notebook_id', sa.String(36), sa.ForeignKey('mistake_notebooks.id'), nullable=False),
            sa.Column('course_id', sa.String(36), sa.ForeignKey('courses.id'), nullable=False),
            sa.Column('exercise_key', sa.String(200), nullable=False),
            sa.Column('rule_hash', sa.String(64), nullable=False),
            sa.Column('objective_ids_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('failed_rounds', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('latest_attempt_id', sa.String(36), sa.ForeignKey('english_check_attempts.id'), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('archived', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('notebook_id', 'course_id', 'exercise_key', 'rule_hash', name='uq_en_aggregate'),
        )
        op.create_index('ix_en_aggregate_scope', 'english_error_aggregates', ['notebook_id', 'course_id', 'archived', 'id'], unique=False)
    if 'english_error_evidence' not in tables:
        op.create_table('english_error_evidence',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('aggregate_id', sa.String(36), sa.ForeignKey('english_error_aggregates.id'), nullable=False),
            sa.Column('attempt_id', sa.String(36), sa.ForeignKey('english_check_attempts.id'), nullable=True, unique=True),
            sa.Column('feedback_id', sa.String(36), sa.ForeignKey('review_feedback.id'), nullable=True, unique=True),
            sa.Column('round_key', sa.String(80), nullable=False),
            sa.Column('valid_error', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_en_evidence_item', 'english_error_evidence', ['aggregate_id', 'round_key', 'id'], unique=False)
    if 'english_review_items' not in tables:
        op.create_table('english_review_items',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('aggregate_id', sa.String(36), sa.ForeignKey('english_error_aggregates.id'), nullable=False, unique=True),
            sa.Column('reason', sa.String(40), nullable=False),
            sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
            sa.Column('retest_task_id', sa.String(36), sa.ForeignKey('retest_tasks.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if 'general_mistake_entries' not in tables:
        op.create_table('general_mistake_entries',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('notebook_id', sa.String(36), sa.ForeignKey('mistake_notebooks.id'), nullable=False),
            sa.Column('course_id', sa.String(36), sa.ForeignKey('courses.id'), nullable=False),
            sa.Column('exercise_key', sa.String(200), nullable=False),
            sa.Column('rule_hash', sa.String(64), nullable=False),
            sa.Column('latest_feedback_id', sa.String(36), sa.ForeignKey('review_feedback.id'), nullable=False),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('archived', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('notebook_id', 'course_id', 'exercise_key', 'rule_hash', name='uq_general_mistake'),
        )
        op.create_index('ix_general_mistake_scope', 'general_mistake_entries', ['notebook_id', 'course_id', 'archived', 'id'], unique=False)
    if 'general_mistake_occurrences' not in tables:
        op.create_table('general_mistake_occurrences',
            sa.Column('id', sa.String(36), primary_key=True, nullable=False),
            sa.Column('entry_id', sa.String(36), sa.ForeignKey('general_mistake_entries.id'), nullable=False),
            sa.Column('feedback_id', sa.String(36), sa.ForeignKey('review_feedback.id'), nullable=False, unique=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

def downgrade():
    raise RuntimeError("English evidence is append-only; restore a verified pre-upgrade backup rather than deleting learning history.")

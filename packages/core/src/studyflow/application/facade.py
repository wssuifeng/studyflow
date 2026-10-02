from __future__ import annotations
from studyflow.infrastructure.runtime import Runtime
from studyflow.modules.planning.service import PlanningService
from studyflow.modules.courses.service import CoursesService
from studyflow.modules.learning.service import LearningService
from studyflow.modules.reviews.service import ReviewsService
from studyflow.modules.documents.service import DocumentsService
from studyflow.modules.workspace.service import WorkspaceService
from studyflow.application.queries import QueriesService
from studyflow.application.demo import DemoService
from datetime import date
from pathlib import Path
from studyflow.infrastructure.config import Settings
from sqlalchemy.orm import Session, sessionmaker
from studyflow.shared.constants import AGENT_SOURCE
from studyflow.modules.planning.repository import ensure_course_membership, require_task, build_plan_summary
from studyflow.modules.learning.repository import latest_attempts, annotate_course
from studyflow.modules.reviews.repository import queue_submissions, decorate_queue


class AppService:
    """Compatibility facade: composes modules, contains no domain rules or SQL."""
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]):
        self.settings = settings
        self.session_factory = session_factory
        self.runtime = Runtime(settings, session_factory)
        self.planning = PlanningService(self.runtime)
        self.courses = CoursesService(self.runtime)
        self.learning = LearningService(self.runtime)
        self.reviews = ReviewsService(self.runtime)
        self.documents = DocumentsService(self.runtime)
        self.queries = QueriesService(self.runtime)
        self.demo = DemoService(self.runtime)
        self.workspace = WorkspaceService(self.runtime, self.queries.dashboard)

    def session(self):
        return self.runtime.session()

    def _event(self, *args, **kwargs):
        return self.runtime.event(*args, **kwargs)

    def create_plan_line(self, name: str, priority: int=1) -> PlanLine:
        return self.planning.create_plan_line(name, priority)

    def get_plan_line(self, identifier: str) -> PlanLine | None:
        return self.planning.get_plan_line(identifier)

    def list_plan_lines(self, include_inactive: bool=False) -> list[PlanLine]:
        return self.planning.list_plan_lines(include_inactive)

    def plan_overviews(self, target_date: date | None=None) -> list[dict]:
        return self.queries.plan_overviews(target_date)

    def get_plan_detail(self, identifier: str, target_date: date | None=None) -> dict | None:
        return self.queries.get_plan_detail(identifier, target_date)

    def _build_plan_summary(self, db: Session, plan: PlanLine, target_date: date, include_courses: bool=False) -> dict:
        return build_plan_summary(db, plan, target_date, include_courses)

    def _ensure_plan_course_item(self, db: Session, plan: PlanLine, course: Course) -> PlanCourseItem:
        return ensure_course_membership(db, plan, course)

    def create_task(self, title: str, scheduled_date: date, task_kind: str='OTHER', description: str='', plan_line_id: str | None=None, stage_id: str | None=None, priority: int=1, course_schedule_item_id: str | None=None) -> Task:
        return self.planning.create_task(title, scheduled_date, task_kind, description, plan_line_id, stage_id, priority, course_schedule_item_id)

    def list_tasks(self, target_date: date | None=None, plan_line_id: str | None=None, task_kind: str | None=None) -> list[Task]:
        return self.planning.list_tasks(target_date, plan_line_id, task_kind)

    def list_courses(self, plan_line_id: str | None=None) -> list[Course]:
        return self.courses.list_courses(plan_line_id)

    def import_course_markdown(self, source_path: str | Path) -> dict:
        return self.courses.import_course_markdown(source_path)

    def seed_demo(self, target_date: date | None=None) -> dict:
        return self.demo.seed_demo(target_date)

    def _latest_attempts(self, db: Session, exercise_ids: list[str], include_drafts: bool=False) -> dict[str, Submission]:
        return latest_attempts(db, exercise_ids, include_drafts)

    def _annotate_course(self, course: Course, item: PlanCourseItem | None, schedule: CourseScheduleItem | None, total: int, latest: dict[str, Submission]) -> None:
        return annotate_course(course, item, schedule, total, latest)

    def _queue_submissions(self, db: Session, plan_line_id: str | None=None) -> list[Submission]:
        return queue_submissions(db, plan_line_id)

    def _decorate_queue(self, submissions: list[Submission]) -> list[Submission]:
        return decorate_queue(submissions)

    def agent_queue(self, plan_line_id: str | None=None) -> dict[str, list[dict]]:
        return self.reviews.agent_queue(plan_line_id)

    def dashboard(self, target_date: date | None=None, plan_line_id: str | None=None, task_kind: str | None=None) -> dict:
        return self.queries.dashboard(target_date, plan_line_id, task_kind)

    def get_course(self, course_id: str) -> Course | None:
        return self.courses.get_course(course_id)

    def plan_detail(self, identifier: str, target_date: date | None=None) -> dict:
        return self.queries.plan_detail(identifier, target_date)

    def course_detail(self, course_id: str) -> dict:
        return self.courses.course_detail(course_id)

    def open_course_study(self, course_id, idempotency_key, new_version=False):
        return self.learning.open_course_study(course_id, idempotency_key, new_version)

    def course_study_detail(self, study_session_id):
        return self.learning.course_study_detail(study_session_id)

    def save_study_progress(self, study_session_id, lesson_id, progress_percent, last_position="", expected_version=None):
        return self.learning.save_study_progress(study_session_id, lesson_id, progress_percent, last_position, expected_version)

    def complete_course_reading(self, study_session_id):
        return self.learning.complete_course_reading(study_session_id)

    def course_answer_sheet(self, course_id: str, study_session_id: str | None = None) -> dict:
        return self.learning.course_answer_sheet(course_id, study_session_id)

    def write_course_answers(self, course_id: str, answers, operation: str, idempotency_key: str, source: str='USER_WEB', study_session_id: str | None = None) -> dict:
        return self.learning.write_course_answers(course_id, answers, operation, idempotency_key, source, study_session_id)

    def submission_detail(self, submission_id: str) -> dict:
        return self.learning.submission_detail(submission_id)

    def get_submission(self, submission_id: str) -> Submission | None:
        return self.learning.get_submission(submission_id)

    def submit_answer(self, exercise_id: str, answer_text: str, task_id: str | None=None, idempotency_key: str | None=None, source: str='USER_WEB') -> Submission:
        return self.learning.submit_answer(exercise_id, answer_text, task_id, idempotency_key, source)

    def _create_followup_submission(self, parent_submission_id: str, answer_text: str, kind: str, idempotency_key: str | None, source: str) -> Submission:
        return self.learning._create_followup_submission(parent_submission_id, answer_text, kind, idempotency_key, source)

    def revise_submission(self, parent_submission_id: str, answer_text: str, idempotency_key: str | None=None, source: str='USER_WEB') -> Submission:
        return self.learning.revise_submission(parent_submission_id, answer_text, idempotency_key, source)

    def retest_submission(self, parent_submission_id: str, answer_text: str, idempotency_key: str | None=None, source: str='USER_WEB') -> Submission:
        return self.learning.retest_submission(parent_submission_id, answer_text, idempotency_key, source)

    def list_pending_submissions(self) -> list[Submission]:
        return self.reviews.list_pending_submissions()

    def write_review(self, submission_id: str, summary: str, detail_markdown: str='', issue_count: int=0, needs_revision: bool=False, idempotency_key: str | None=None, source: str=AGENT_SOURCE, *, decision: str | None=None, next_action: str='') -> ReviewFeedback:
        return self.reviews.write_review(submission_id, summary, detail_markdown, issue_count, needs_revision, idempotency_key, source, decision=decision, next_action=next_action)

    def update_task_status(self, task_id: str, target: str, reason: str='', next_action: str='') -> Task:
        return self.planning.update_task_status(task_id, target, reason, next_action)

    def check_document(self, relative_path: str) -> Document:
        return self.documents.check_document(relative_path)

    def list_documents(self) -> list[Document]:
        return self.documents.list_documents()

    def read_document(self, relative_path: str, render: bool=True) -> dict:
        return self.documents.read_document(relative_path, render)

    def _replay_submission_write(self, db: Session, key: str | None, operation: str, exercise_id: str | None=None, submission_id: str | None=None) -> Submission | None:
        return self.learning._replay_submission_write(db, key, operation, exercise_id, submission_id)

    def _record_submission_write(self, db: Session, key: str | None, operation: str, row: Submission) -> None:
        return self.learning._record_submission_write(db, key, operation, row)

    def _check_task(self, db: Session, task_id: str | None) -> Task | None:
        return require_task(db, task_id)

    def save_submission_draft(self, exercise_id: str, answer_text: str='', submission_id: str | None=None, task_id: str | None=None, idempotency_key: str | None=None, source: str='USER_WEB', expected_version: int | None=None) -> Submission:
        return self.learning.save_submission_draft(exercise_id, answer_text, submission_id, task_id, idempotency_key, source, expected_version)

    def submit_submission(self, exercise_id: str | None=None, answer_text: str | None=None, submission_id: str | None=None, task_id: str | None=None, idempotency_key: str | None=None, source: str='USER_WEB', expected_version: int | None=None) -> Submission:
        return self.learning.submit_submission(exercise_id, answer_text, submission_id, task_id, idempotency_key, source, expected_version)

    def save_learning_progress(self, course_id: str, lesson_id: str, progress_percent: int, last_position: str='', source: str='USER_ENGINE') -> LearningProgress:
        return self.learning.save_learning_progress(course_id, lesson_id, progress_percent, last_position, source)

    def generate_snapshot(self, target_date: date | None=None, scope: str='today') -> ContextSnapshot:
        return self.workspace.generate_snapshot(target_date, scope)

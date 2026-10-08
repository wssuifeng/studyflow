from __future__ import annotations
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from studyflow.modules.courses.models import Course
from studyflow.modules.planning.models import CourseScheduleItem, PlanCourseItem
from studyflow.modules.learning.models import Submission
from studyflow.shared.constants import PASSED_STATES




def latest_attempts(db: Session, exercise_ids: list[str], include_drafts: bool = False) -> dict[str, Submission]:
    if not exercise_ids:
        return {}
    query = select(Submission).where(Submission.exercise_id.in_(exercise_ids))
    if not include_drafts:
        query = query.where(Submission.status != "DRAFT")
    rows = db.scalars(query.order_by(Submission.attempt_number, Submission.created_at)).all()
    latest: dict[str, Submission] = {}
    from .write_contract import effective_rows
    for row in effective_rows(db, rows):
        current = latest.get(row.exercise_id)
        if current is None or (row.attempt_number, row.created_at or datetime.min) >= (current.attempt_number, current.created_at or datetime.min):
            latest[row.exercise_id] = row
    return latest


def annotate_course(course: Course, item: PlanCourseItem | None, schedule: CourseScheduleItem | None, total: int, latest: dict[str, Submission]) -> None:
    exercises = [exercise for lesson in course.lessons for exercise in lesson.exercises]
    completed = sum(1 for exercise in exercises if latest.get(exercise.id) and latest[exercise.id].status in PASSED_STATES)
    knowledge_completed = 0
    for lesson in course.lessons:
        lesson_exercises = list(lesson.exercises)
        done = bool(lesson_exercises) and all(latest.get(exercise.id) and latest[exercise.id].status in PASSED_STATES for exercise in lesson_exercises)
        if done:
            knowledge_completed += 1
        setattr(lesson, "progress_state", "DONE" if done else "TODO")
    from .study_sessions import current_study, outcome
    from sqlalchemy.orm import object_session
    db = object_session(course)
    study = current_study(db,course.id) if db else None
    if study:
        state = outcome(db,study)
        completed = state["exercise_completed"]
        setattr(course,"study_status",state["study_status"])
        setattr(course,"learning_submitted",state["learning_submitted"])
        setattr(course,"study_session_id",study.id)
        setattr(course,"waiting_count",state["waiting_count"])
        setattr(course,"feedback_count",state["feedback_count"])
        setattr(course,"frozen_exercise_total",state["exercise_total"])
    else:
        formal = [latest[ex.id] for ex in exercises if ex.id in latest]
        submitted = bool(exercises) and len(formal) == len(exercises)
        state = "PASSED" if exercises and completed == len(exercises) else "NEEDS_REVISION" if any(row.status=="NEEDS_REVISION" for row in formal) else "RETEST_REQUIRED" if any(row.status=="RETEST_REQUIRED" for row in formal) else "WAITING_REVIEW" if submitted else "NOT_STARTED"
        setattr(course,"study_status",state)
        setattr(course,"learning_submitted",submitted)
    setattr(course, "planned_start", item.planned_start if item else None)
    setattr(course, "planned_end", item.planned_end if item else None)
    setattr(course, "plan_sequence", item.sequence_number if item else None)
    setattr(course, "plan_total", total)
    setattr(course, "schedule_item", schedule)
    setattr(course, "knowledge_total", len(course.lessons))
    setattr(course, "knowledge_completed", knowledge_completed)
    setattr(course, "exercise_total", getattr(course,"frozen_exercise_total",len(exercises)))
    setattr(course, "exercise_completed", completed)
    setattr(course, "progress_percent", round(completed / course.exercise_total * 100) if course.exercise_total else 100 if getattr(course,"study_status",None)=="READ_COMPLETED" else 0)

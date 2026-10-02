from __future__ import annotations
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.models import Course, Lesson
from studyflow.modules.planning.models import CourseScheduleItem, PlanCourseItem, PlanLine, Task
from studyflow.shared.ids import new_id
from studyflow.modules.learning.repository import latest_attempts, annotate_course




def ensure_course_membership(db: Session, plan: PlanLine, course: Course) -> PlanCourseItem:
    item = db.scalar(select(PlanCourseItem).where(PlanCourseItem.plan_line_id == plan.id, PlanCourseItem.course_id == course.id))
    if item:
        return item
    next_sequence = db.scalar(select(func.max(PlanCourseItem.sequence_number)).where(PlanCourseItem.plan_line_id == plan.id)) or 0
    item = PlanCourseItem(id=new_id(), plan_line_id=plan.id, course_id=course.id, sequence_number=next_sequence + 1)
    db.add(item)
    db.flush()
    return item


def require_task(db: Session, task_id: str | None) -> Task | None:
    task = db.get(Task, task_id) if task_id else None
    if task_id and task is None:
        raise DomainError("OBJECT_NOT_FOUND", "任务不存在。", "先读取今日任务确认 task_id。")
    return task


def build_plan_summary(db: Session, plan: PlanLine, target_date: date, include_courses: bool = False) -> dict:
    items = db.scalars(select(PlanCourseItem).options(
        joinedload(PlanCourseItem.course).joinedload(Course.lessons).joinedload(Lesson.exercises),
        joinedload(PlanCourseItem.course).joinedload(Course.plan_line),
    ).where(PlanCourseItem.plan_line_id == plan.id).order_by(PlanCourseItem.sequence_number)).unique().all()
    exercise_ids = [exercise.id for item in items for lesson in item.course.lessons for exercise in lesson.exercises]
    latest = latest_attempts(db, exercise_ids)
    schedules = []
    if items:
        schedules = db.scalars(select(CourseScheduleItem).where(
            CourseScheduleItem.plan_course_item_id.in_([item.id for item in items]),
            CourseScheduleItem.scheduled_date == target_date,
        )).all()
    schedule_by_item = {schedule.plan_course_item_id: schedule for schedule in schedules}
    courses = []
    completed_courses = 0
    current_course = None
    for item in items:
        annotate_course(item.course, item, schedule_by_item.get(item.id), len(items), latest)
        if item.course.progress_percent >= 100:
            completed_courses += 1
        if current_course is None and not item.course.learning_submitted:
            current_course = item.course
        courses.append(item.course)
    progress = round(completed_courses / len(courses) * 100) if courses else 0
    summary = {
        "id": plan.id,
        "name": plan.name,
        "priority": plan.priority,
        "status": plan.status,
        "course_total": len(courses),
        "completed_courses": completed_courses,
        "progress_percent": progress,
        "current_course": current_course,
        "today_course_count": sum(1 for course in courses if course.schedule_item),
        "target_date": target_date,
    }
    if include_courses:
        summary["courses"] = courses
    return summary

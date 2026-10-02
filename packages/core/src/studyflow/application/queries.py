from __future__ import annotations
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from studyflow.modules.courses.presentation import course_summary
from studyflow.shared.domain import TASK_KINDS, DomainError
from studyflow.modules.courses.models import Course, Lesson
from studyflow.modules.planning.models import CourseScheduleItem, PlanCourseItem, PlanLine, Task
from studyflow.modules.planning.repository import build_plan_summary
from studyflow.modules.learning.repository import latest_attempts, annotate_course
from studyflow.modules.reviews.repository import queue_submissions, decorate_queue


from studyflow.infrastructure.runtime import Runtime, Service


class QueriesService(Service):
    def plan_overviews(self, target_date: date | None = None) -> list[dict]:
        target_date = target_date or date.today()
        with self.session() as db:
            plans = db.scalars(select(PlanLine).where(PlanLine.status == "ACTIVE").order_by(PlanLine.priority, PlanLine.name)).all()
            result = []
            for plan in plans:
                result.append(build_plan_summary(db, plan, target_date))
            return result

    def get_plan_detail(self, identifier: str, target_date: date | None = None) -> dict | None:
        target_date = target_date or date.today()
        with self.session() as db:
            plan = db.scalar(select(PlanLine).where((PlanLine.id == identifier) | (PlanLine.name == identifier)))
            if not plan:
                return None
            return build_plan_summary(db, plan, target_date, include_courses=True)

    def dashboard(self, target_date: date | None = None, plan_line_id: str | None = None, task_kind: str | None = None) -> dict:
        target_date = target_date or date.today()
        with self.session() as db:
            task_query = select(Task).options(joinedload(Task.time_blocks), joinedload(Task.plan_line), joinedload(Task.course_schedule_item)).where(Task.scheduled_date == target_date).order_by(Task.priority, Task.id)
            if plan_line_id:
                task_query = task_query.where(Task.plan_line_id == plan_line_id)
            if task_kind:
                if task_kind.upper() not in TASK_KINDS:
                    raise DomainError("INVALID_TASK_KIND", f"不支持的任务类型：{task_kind}", f"可用类型：{', '.join(sorted(TASK_KINDS))}")
                task_query = task_query.where(Task.task_kind == task_kind.upper())
            tasks = db.scalars(task_query).unique().all()

            item_query = select(PlanCourseItem).options(
                joinedload(PlanCourseItem.plan_line),
                joinedload(PlanCourseItem.course).joinedload(Course.plan_line),
                joinedload(PlanCourseItem.course).joinedload(Course.lessons).joinedload(Lesson.exercises),
            ).join(Course, Course.id == PlanCourseItem.course_id).where(Course.status == "ACTIVE").order_by(PlanCourseItem.plan_line_id, PlanCourseItem.sequence_number)
            if plan_line_id:
                item_query = item_query.where(PlanCourseItem.plan_line_id == plan_line_id)
            plan_items = db.scalars(item_query).unique().all()
            schedule_query = select(CourseScheduleItem).options(
                joinedload(CourseScheduleItem.plan_course_item).joinedload(PlanCourseItem.plan_line),
                joinedload(CourseScheduleItem.plan_course_item).joinedload(PlanCourseItem.course).joinedload(Course.lessons).joinedload(Lesson.exercises),
            ).where(CourseScheduleItem.scheduled_date == target_date).order_by(CourseScheduleItem.position, CourseScheduleItem.start_time)
            if plan_line_id:
                schedule_query = schedule_query.join(CourseScheduleItem.plan_course_item).where(PlanCourseItem.plan_line_id == plan_line_id)
            schedules = db.scalars(schedule_query).unique().all()
            by_course = {item.course.id: item for item in plan_items}
            total_by_plan: dict[str, int] = {}
            for item in plan_items:
                total_by_plan[item.plan_line_id] = total_by_plan.get(item.plan_line_id, 0) + 1
            exercise_ids = [exercise.id for item in plan_items for lesson in item.course.lessons for exercise in lesson.exercises]
            latest = latest_attempts(db, exercise_ids)
            courses: list[Course] = []
            seen: set[str] = set()
            for schedule in schedules:
                course = schedule.plan_course_item.course
                if course.id not in seen:
                    annotate_course(course, by_course.get(course.id), schedule, total_by_plan.get(schedule.plan_course_item.plan_line_id, 0), latest)
                    courses.append(course)
                    seen.add(course.id)
            for item in plan_items:
                if item.course.id not in seen:
                    annotate_course(item.course, item, None, total_by_plan.get(item.plan_line_id, 0), latest)
                    courses.append(item.course)
                    seen.add(item.course.id)

            pending = decorate_queue(queue_submissions(db, plan_line_id))
            plans = db.scalars(select(PlanLine).where(PlanLine.status == "ACTIVE").order_by(PlanLine.priority, PlanLine.name)).all()
            queue = {
                "waiting_review": [x for x in pending if x.status == "WAITING_REVIEW"],
                "needs_revision": [x for x in pending if x.status == "NEEDS_REVISION"],
                "waiting_retest": [x for x in pending if x.status == "RETEST_REQUIRED"],
                "items": pending,
            }
            current_course = next((course for course in courses if not course.learning_submitted), None)
            return {
                "date": target_date,
                "tasks": tasks,
                "courses": courses,
                "pending": pending,
                "agent_queue": queue,
                "queue_counts": {"waiting_review": len(queue["waiting_review"]), "needs_revision": len(queue["needs_revision"]), "waiting_retest": len(queue["waiting_retest"])},
                "plans": plans,
                "plan_line_id": plan_line_id,
                "task_kind": task_kind,
                "primary_task": tasks[0] if tasks else None,
                "current_course": current_course,
                "course_position": current_course.plan_sequence if current_course else None,
                "course_total": current_course.plan_total if current_course else 0,
            }

    def plan_detail(self, identifier: str, target_date: date | None = None) -> dict:
        detail = self.get_plan_detail(identifier, target_date)
        if detail is None:
            raise DomainError("OBJECT_NOT_FOUND", "学习计划不存在。", "先读取 plan.list 确认计划 ID。")
        return {"plan": {key: value for key, value in detail.items() if key not in {"courses", "current_course", "target_date"}},
                "target_date": detail["target_date"],
                "current_course": course_summary(detail["current_course"]) if detail["current_course"] else None,
                "courses": [course_summary(course) for course in detail.get("courses", [])],
                "next_action": "按课程序号进入当前课程。"}

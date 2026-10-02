from __future__ import annotations
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from studyflow.shared.domain import TASK_KINDS, DomainError, validate_task_transition
from studyflow.modules.planning.models import CourseScheduleItem, PlanLine, Stage, Task
from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE


from studyflow.infrastructure.runtime import Runtime, Service


class PlanningService(Service):
    def create_plan_line(self, name: str, priority: int = 1) -> PlanLine:
        normalized = name.strip()
        if not normalized:
            raise DomainError("INVALID_ARGUMENT", "计划线名称不能为空。", "提供有意义的计划线名称。")
        if priority < 1:
            raise DomainError("INVALID_ARGUMENT", "优先级必须大于等于 1。", "将优先级设置为正整数。")
        with self.session() as db:
            existing = db.scalar(select(PlanLine).where(PlanLine.name == normalized))
            if existing:
                raise DomainError("PLAN_LINE_EXISTS", f"计划线已存在：{normalized}", "使用 plan list 查看现有计划线。")
            plan = PlanLine(id=new_id(), name=normalized, priority=priority)
            db.add(plan)
            db.flush()
            self._event(db, AGENT_SOURCE, "plan_line", plan.id, "CREATE", normalized)
            return plan

    def get_plan_line(self, identifier: str) -> PlanLine | None:
        with self.session() as db:
            return db.scalar(select(PlanLine).where((PlanLine.id == identifier) | (PlanLine.name == identifier)))

    def list_plan_lines(self, include_inactive: bool = False) -> list[PlanLine]:
        with self.session() as db:
            query = select(PlanLine).order_by(PlanLine.priority, PlanLine.name)
            if not include_inactive:
                query = query.where(PlanLine.status == "ACTIVE")
            return db.scalars(query).all()

    def create_task(
        self,
        title: str,
        scheduled_date: date,
        task_kind: str = "OTHER",
        description: str = "",
        plan_line_id: str | None = None,
        stage_id: str | None = None,
        priority: int = 1,
        course_schedule_item_id: str | None = None,
    ) -> Task:
        normalized_title = title.strip()
        kind = task_kind.strip().upper()
        if not normalized_title:
            raise DomainError("INVALID_ARGUMENT", "任务标题不能为空。", "填写任务标题后重试。")
        if kind not in TASK_KINDS:
            raise DomainError("INVALID_TASK_KIND", f"不支持的任务类型：{task_kind}", f"可用类型：{', '.join(sorted(TASK_KINDS))}")
        if priority < 1:
            raise DomainError("INVALID_ARGUMENT", "优先级必须大于等于 1。", "将优先级设置为正整数。")
        with self.session() as db:
            plan = db.get(PlanLine, plan_line_id) if plan_line_id else None
            if plan_line_id and not plan:
                raise DomainError("PLAN_LINE_NOT_FOUND", "计划线不存在。", "使用 plan list 获取有效计划线 ID。")
            stage = db.get(Stage, stage_id) if stage_id else None
            if stage_id and not stage:
                raise DomainError("STAGE_NOT_FOUND", "阶段不存在。", "使用有效阶段 ID，或省略阶段。")
            if stage and plan and stage.plan_line_id != plan.id:
                raise DomainError("STAGE_PLAN_MISMATCH", "任务阶段与计划线不匹配。", "选择同一计划线下的阶段。")
            schedule = db.get(CourseScheduleItem, course_schedule_item_id) if course_schedule_item_id else None
            if course_schedule_item_id and not schedule:
                raise DomainError("SCHEDULE_NOT_FOUND", "课程日程窗口不存在。", "使用有效的课程日程 ID。")
            if schedule and plan and schedule.plan_course_item.plan_line_id != plan.id:
                raise DomainError("SCHEDULE_PLAN_MISMATCH", "课程日程与计划线不匹配。", "选择同一学习计划下的课程日程。")
            if stage and not plan:
                plan = db.get(PlanLine, stage.plan_line_id)
            task = Task(
                id=new_id(), plan_line_id=plan.id if plan else None, stage_id=stage.id if stage else None,
                course_schedule_item_id=schedule.id if schedule else None,
                title=normalized_title, description=description.strip(), scheduled_date=scheduled_date,
                task_kind=kind, priority=priority,
            )
            db.add(task)
            db.flush()
            self._event(db, AGENT_SOURCE, "task", task.id, "CREATE", normalized_title)
            return task

    def list_tasks(
        self, target_date: date | None = None, plan_line_id: str | None = None, task_kind: str | None = None
    ) -> list[Task]:
        with self.session() as db:
            query = select(Task).options(joinedload(Task.plan_line), joinedload(Task.time_blocks)).order_by(Task.scheduled_date, Task.priority, Task.title)
            if target_date:
                query = query.where(Task.scheduled_date == target_date)
            if plan_line_id:
                query = query.where(Task.plan_line_id == plan_line_id)
            if task_kind:
                kind = task_kind.upper()
                if kind not in TASK_KINDS:
                    raise DomainError("INVALID_TASK_KIND", f"不支持的任务类型：{task_kind}", f"可用类型：{', '.join(sorted(TASK_KINDS))}")
                query = query.where(Task.task_kind == kind)
            return db.scalars(query).unique().all()

    def update_task_status(self, task_id: str, target: str, reason: str = "", next_action: str = "") -> Task:
        with self.session() as db:
            task = db.get(Task, task_id)
            if not task:
                raise DomainError("OBJECT_NOT_FOUND", "任务不存在")
            validate_task_transition(task.status, target, reason, next_action)
            task.status, task.reason, task.next_action = target, reason, next_action
            self._event(db, "USER_WEB", "task", task.id, "STATUS", f"{task.status} → {target}")
            return task

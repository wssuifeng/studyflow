from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
import re
from typing import Iterator
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from .presentation import course_detail, course_summary, submission_detail
from .config import Settings
from .domain import (
    COURSE_CONTENT_TYPES,
    DOCUMENT_TYPES,
    EXERCISE_TYPES,
    TASK_KINDS,
    DomainError,
    normalize_review_decision,
    validate_submission_status,
    validate_task_transition,
)
from .markdown import inspect_document, parse_front_matter, resolve_import_path, safe_resolve, validate_import_metadata
from .models import (
    ContextSnapshot,
    Course,
    CourseScheduleItem,
    Document,
    EventLog,
    Exercise,
    Lesson,
    LearningProgress,
    PlanCourseItem,
    PlanLine,
    ReviewFeedback,
    Stage,
    Submission,
    SubmissionWriteReceipt,
    Task,
    TimeBlock,
)


AGENT_SOURCE = "AGENT_CLI"
PASSED_STATES = {"PASSED", "RECHECKED", "REVIEWED"}
QUEUE_STATUSES = {"WAITING_REVIEW", "NEEDS_REVISION", "RETEST_REQUIRED"}
FOLLOWUP_ALLOWED_STATUSES = {"REVIEWED", "NEEDS_REVISION", "RETEST_REQUIRED", "PASSED", "RECHECKED"}


def new_id() -> str:
    return str(uuid4())


def _decode_escaped_text(value: str) -> str:
    """Repair legacy seed data that accidentally stored literal unicode escapes."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)


class AppService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]):
        self.settings = settings
        self.session_factory = session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _event(self, session: Session, source: str, object_type: str, object_id: str, action: str, summary: str) -> None:
        session.add(EventLog(id=new_id(), source=source, object_type=object_type, object_id=object_id, action=action, summary=summary))

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

    def plan_overviews(self, target_date: date | None = None) -> list[dict]:
        target_date = target_date or date.today()
        with self.session() as db:
            plans = db.scalars(select(PlanLine).where(PlanLine.status == "ACTIVE").order_by(PlanLine.priority, PlanLine.name)).all()
            result = []
            for plan in plans:
                result.append(self._build_plan_summary(db, plan, target_date))
            return result

    def get_plan_detail(self, identifier: str, target_date: date | None = None) -> dict | None:
        target_date = target_date or date.today()
        with self.session() as db:
            plan = db.scalar(select(PlanLine).where((PlanLine.id == identifier) | (PlanLine.name == identifier)))
            if not plan:
                return None
            return self._build_plan_summary(db, plan, target_date, include_courses=True)

    def _build_plan_summary(self, db: Session, plan: PlanLine, target_date: date, include_courses: bool = False) -> dict:
        items = db.scalars(select(PlanCourseItem).options(
            joinedload(PlanCourseItem.course).joinedload(Course.lessons).joinedload(Lesson.exercises),
            joinedload(PlanCourseItem.course).joinedload(Course.plan_line),
        ).where(PlanCourseItem.plan_line_id == plan.id).order_by(PlanCourseItem.sequence_number)).unique().all()
        exercise_ids = [exercise.id for item in items for lesson in item.course.lessons for exercise in lesson.exercises]
        latest = self._latest_attempts(db, exercise_ids)
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
            self._annotate_course(item.course, item, schedule_by_item.get(item.id), len(items), latest)
            if item.course.progress_percent >= 100:
                completed_courses += 1
            elif current_course is None:
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

    def _ensure_plan_course_item(self, db: Session, plan: PlanLine, course: Course) -> PlanCourseItem:
        item = db.scalar(select(PlanCourseItem).where(PlanCourseItem.plan_line_id == plan.id, PlanCourseItem.course_id == course.id))
        if item:
            return item
        next_sequence = db.scalar(select(func.max(PlanCourseItem.sequence_number)).where(PlanCourseItem.plan_line_id == plan.id)) or 0
        item = PlanCourseItem(id=new_id(), plan_line_id=plan.id, course_id=course.id, sequence_number=next_sequence + 1)
        db.add(item)
        db.flush()
        return item

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

    def list_courses(self, plan_line_id: str | None = None) -> list[Course]:
        with self.session() as db:
            if plan_line_id:
                query = select(Course).join(PlanCourseItem, PlanCourseItem.course_id == Course.id).options(joinedload(Course.plan_line), joinedload(Course.lessons).joinedload(Lesson.exercises)).where(Course.status == "ACTIVE", PlanCourseItem.plan_line_id == plan_line_id).order_by(PlanCourseItem.sequence_number, Course.title)
            else:
                query = select(Course).options(joinedload(Course.plan_line), joinedload(Course.lessons).joinedload(Lesson.exercises)).where(Course.status == "ACTIVE").order_by(Course.title)
            return db.scalars(query).unique().all()

    def import_course_markdown(self, source_path: str | Path) -> dict:
        path, relative_path = resolve_import_path(self.settings.workspace_root, source_path)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DomainError("DOCUMENT_UNREADABLE", f"Markdown 文件无法读取：{relative_path}", "确认文件使用 UTF-8 编码且当前用户有读取权限。") from exc
        raw_metadata, _ = parse_front_matter(content)
        metadata = validate_import_metadata(raw_metadata)
        content_type = str(metadata.get("content_type", "LESSON")).strip().upper()
        if content_type not in COURSE_CONTENT_TYPES:
            raise DomainError("INVALID_CONTENT_TYPE", f"不支持的课程内容类型：{content_type}", f"可用类型：{', '.join(sorted(COURSE_CONTENT_TYPES))}")
        document_type = str(metadata.get("document_type", "LESSON")).strip().upper()
        if document_type not in DOCUMENT_TYPES:
            raise DomainError("INVALID_DOCUMENT_TYPE", f"不支持的文档类型：{document_type}", f"可用类型：{', '.join(sorted(DOCUMENT_TYPES))}")
        normalized_exercises = []
        for item in metadata["exercises"]:
            title = item.get("title")
            prompt = item.get("prompt")
            if not isinstance(title, str) or not title.strip() or not isinstance(prompt, str) or not prompt.strip():
                raise DomainError("INVALID_EXERCISE_METADATA", "每个练习都必须提供 title 和 prompt。", "补全 Front Matter 中练习标题与题面。")
            exercise_type = str(item.get("type", "SHORT_ANSWER")).strip().upper()
            if exercise_type not in EXERCISE_TYPES:
                raise DomainError("INVALID_EXERCISE_TYPE", f"不支持的练习类型：{exercise_type}", f"可用类型：{', '.join(sorted(EXERCISE_TYPES))}")
            normalized_exercises.append((title.strip(), prompt.strip(), str(item.get("requirements", "")).strip(), exercise_type))

        with self.session() as db:
            existing_lesson = db.scalar(select(Lesson).where(Lesson.markdown_path == relative_path))
            if existing_lesson:
                course = db.get(Course, existing_lesson.course_id)
                if course and course.plan_line_id:
                    plan = db.get(PlanLine, course.plan_line_id)
                    if plan:
                        self._ensure_plan_course_item(db, plan, course)
                return {"created": False, "course_id": course.id, "lesson_id": existing_lesson.id, "path": relative_path}
            plan_name = metadata["plan_line"]
            plan = db.scalar(select(PlanLine).where(PlanLine.name == plan_name))
            if not plan:
                raise DomainError("PLAN_LINE_NOT_FOUND", f"计划线不存在：{plan_name}", "先使用 studyflow plan create 创建计划线，再导入课程。")
            course_title = metadata["course"]
            course = db.scalar(select(Course).where(Course.plan_line_id == plan.id, Course.title == course_title))
            if not course:
                course = Course(
                    id=new_id(), plan_line_id=plan.id, title=course_title,
                    summary=str(metadata.get("summary", "")).strip(), subject=str(metadata.get("subject", "")).strip(),
                    content_type=content_type, difficulty=str(metadata.get("difficulty", "")).strip().upper(),
                    source_type=str(metadata.get("source_type", AGENT_SOURCE)).strip().upper(),
                )
                db.add(course)
                db.flush()
            plan_course_item = self._ensure_plan_course_item(db, plan, course)
            position = db.scalar(select(func.max(Lesson.position)).where(Lesson.course_id == course.id)) or 0
            lesson = Lesson(id=new_id(), course_id=course.id, title=metadata["lesson"], position=position + 1, markdown_path=relative_path, summary=str(metadata.get("summary", "")).strip())
            for index, (title, prompt, requirements, exercise_type) in enumerate(normalized_exercises, start=1):
                lesson.exercises.append(Exercise(id=new_id(), title=title, prompt=prompt, requirements=requirements, exercise_type=exercise_type, position=index))
            db.add(lesson)
            inspection = inspect_document(self.settings.workspace_root, relative_path)
            document = db.scalar(select(Document).where(Document.relative_path == relative_path))
            if not document:
                document = Document(id=new_id(), relative_path=relative_path)
                db.add(document)
            document.document_type = document_type
            document.status = inspection.status
            document.file_size = inspection.file_size
            document.modified_at = inspection.modified_at
            document.content_hash = inspection.content_hash
            db.flush()
            self._event(db, AGENT_SOURCE, "course", course.id, "IMPORT_MARKDOWN", relative_path)
            return {"created": True, "course_id": course.id, "lesson_id": lesson.id, "plan_course_item_id": plan_course_item.id, "path": relative_path, "course_title": course.title}

    def seed_demo(self, target_date: date | None = None) -> dict:
        target_date = target_date or date.today()
        lesson_specs = [
            (
                "\u5bf9\u8c61\u3001\u5f15\u7528\u4e0e\u65b9\u6cd5\u8c03\u7528",
                "\u628a\u8bed\u8a00\u8bed\u4e49\u3001JVM \u62bd\u8c61\u548c\u5b9e\u73b0\u76f4\u89c9\u5206\u5f00\u3002",
                "\u7528\u81ea\u5df1\u7684\u8bdd\u89e3\u91ca\u5f15\u7528\u503c\u526f\u672c\u4e0e\u5bf9\u8c61\u5b57\u6bb5\u4fee\u6539\u3002",
                "\u8bf7\u89e3\u91ca\uff1a\u8c03\u7528 device.updateStatus() \u540e\uff0c\u4e3a\u4ec0\u4e48\u8c03\u7528\u65b9\u770b\u5230 device.status \u53d1\u751f\u53d8\u5316\uff1f\u540c\u65f6\u8bf4\u660e Java \u662f\u5426\u5b58\u5728\u53ef\u76f4\u63a5\u8fdb\u884c\u6307\u9488\u8fd0\u7b97\u7684\u6307\u9488\u3002",
                "\u81f3\u5c11\u5199\u51fa\uff1a\u503c\u4f20\u9012\u3001\u5f15\u7528\u503c\u526f\u672c\u3001\u540c\u4e00\u5bf9\u8c61\u5b57\u6bb5\u3001\u4e0d\u80fd\u8fdb\u884c\u5730\u5740\u8fd0\u7b97\u56db\u4e2a\u8981\u70b9\u3002",
            ),
            (
                "equals \u4e0e hashCode \u5951\u7ea6",
                "\u7406\u89e3\u5bf9\u8c61\u76f8\u7b49\u5224\u65ad\u4e0e\u54c8\u5e0c\u96c6\u5408\u884c\u4e3a\u4e4b\u95f4\u7684\u7ea6\u675f\u3002",
                "\u8bf4\u660e equals/hashCode \u7684\u4e00\u81f4\u6027\u3002",
                "\u8bf7\u8bf4\u660e\u91cd\u5199 equals \u540e\u4e3a\u4ec0\u4e48\u901a\u5e38\u4e5f\u5fc5\u987b\u91cd\u5199 hashCode\uff0c\u5e76\u4e3e\u51fa\u653e\u5165 HashSet \u7684\u5f71\u54cd\u3002",
                "\u81f3\u5c11\u5199\u51fa\uff1a\u76f8\u7b49\u5bf9\u8c61\u5fc5\u987b\u62e5\u6709\u76f8\u540c hashCode\u3001HashSet \u67e5\u627e\u4f9d\u8d56\u4e24\u8005\u3001\u7834\u574f\u5951\u7ea6\u7684\u540e\u679c\u3002",
            ),
            (
                "\u5f02\u5e38\u94fe\u4e0e\u7edf\u4e00\u9519\u8bef\u5904\u7406",
                "\u7406\u89e3\u5f02\u5e38\u5305\u88c5\u3001\u6839\u56e0\u4fdd\u7559\u548c\u7edf\u4e00\u5904\u7406\u8fb9\u754c\u3002",
                "\u8bbe\u8ba1\u4e00\u4e2a\u53ef\u8ffd\u8e2a\u6839\u56e0\u7684\u5f02\u5e38\u5904\u7406\u65b9\u6848\u3002",
                "\u8bf7\u89e3\u91ca\u4e3a\u4ec0\u4e48\u4e1a\u52a1\u5c42\u4e0d\u5e94\u53ea\u629b\u51fa\u4e00\u4e2a\u4e22\u5931\u6839\u56e0\u7684\u901a\u7528\u5f02\u5e38\uff0c\u4ee5\u53ca\u5982\u4f55\u4fdd\u7559 cause \u5e76\u5728\u8fb9\u754c\u7edf\u4e00\u8f6c\u6362\u3002",
                "\u81f3\u5c11\u5199\u51fa\uff1a\u539f\u59cb cause\u3001\u5f02\u5e38\u8fb9\u754c\u3001\u7528\u6237\u53ef\u8bfb\u9519\u8bef\u3001\u65e5\u5fd7\u8ffd\u8e2a\u56db\u4e2a\u8981\u70b9\u3002",
            ),
        ]
        with self.session() as db:
            existing = db.scalar(select(PlanLine).where(PlanLine.name.like("Java%")))
            if existing:
                existing.name = "Java\u5c31\u4e1a"
                course = db.scalar(select(Course).where(Course.plan_line_id == existing.id, Course.title.like("Java%")))
                if not course:
                    course = db.scalar(select(Course).where(Course.plan_line_id == existing.id).order_by(Course.created_at))
                if course:
                    course.title = "Java\u5bf9\u8c61\u6a21\u578b\uff1a\u4ece\u5f15\u7528\u5230\u8fd0\u884c\u8fc7\u7a0b"
                    course.summary = "\u7528\u591a\u4e2a\u77e5\u8bc6\u70b9\u548c\u53ef\u8fd0\u884c\u7684\u5c0f\u7ec3\u4e60\u7406\u89e3\u5bf9\u8c61\u3001\u5f15\u7528\u3001\u5951\u7ea6\u4e0e\u5f02\u5e38\u8fb9\u754c\u3002"
                    item = self._ensure_plan_course_item(db, existing, course)
                    existing_lessons = sorted(course.lessons, key=lambda lesson: lesson.position)
                    for position, (title, summary, exercise_title, prompt, requirements) in enumerate(lesson_specs, start=1):
                        lesson = existing_lessons[position - 1] if position <= len(existing_lessons) else None
                        if lesson is None:
                            lesson = Lesson(id=new_id(), course_id=course.id, title=title, position=position, markdown_path="content/lessons/java-reference.md", summary=summary)
                            db.add(lesson)
                        lesson.title = title
                        lesson.position = position
                        lesson.summary = summary
                        lesson.markdown_path = "content/lessons/java-reference.md"
                        if lesson.exercises:
                            exercise = sorted(lesson.exercises, key=lambda item: item.position)[0]
                            exercise.title = exercise_title
                            exercise.prompt = prompt
                            exercise.requirements = requirements
                        else:
                            lesson.exercises.append(Exercise(id=new_id(), title=exercise_title, position=1, prompt=prompt, requirements=requirements))
                    if not db.scalar(select(CourseScheduleItem).where(CourseScheduleItem.plan_course_item_id == item.id, CourseScheduleItem.scheduled_date == target_date)):
                        db.add(CourseScheduleItem(id=new_id(), plan_course_item_id=item.id, scheduled_date=target_date, position=1, start_time=time(9, 0), end_time=time(10, 30)))
                return {"created": False, "plan_line_id": existing.id, "course_id": course.id if course else None}
            plan = PlanLine(id=new_id(), name="Java\u5c31\u4e1a", priority=1)
            stage = Stage(id=new_id(), plan_line=plan, name="StudyFlow\u4ea7\u54c1\u7b2c\u4e00\u6761\u95ed\u73af", window_start=target_date, window_end=target_date)
            task = Task(id=new_id(), stage=stage, title="\u5b8c\u6210 StudyFlow \u7b2c\u4e00\u8282\u8bfe\u7a0b\u4e0e\u7ec3\u4e60", description="\u9605\u8bfb\u8bfe\u7a0b\uff0c\u5b8c\u6210\u7ec3\u4e60\u5e76\u63d0\u4ea4\u7b54\u6848\uff0c\u4e4b\u540e\u7531\u5916\u90e8 Agent \u901a\u8fc7 CLI \u6279\u6539\u3002", scheduled_date=target_date, priority=1, task_kind="PRACTICE")
            task.time_blocks.append(TimeBlock(id=new_id(), block_date=target_date, start_time=time(9, 0), end_time=time(10, 30)))
            course = Course(id=new_id(), plan_line=plan, title="Java\u5bf9\u8c61\u6a21\u578b\uff1a\u4ece\u5f15\u7528\u5230\u8fd0\u884c\u8fc7\u7a0b", summary="\u7528\u591a\u4e2a\u77e5\u8bc6\u70b9\u548c\u53ef\u8fd0\u884c\u7684\u5c0f\u7ec3\u4e60\u7406\u89e3\u5bf9\u8c61\u3001\u5f15\u7528\u3001\u5951\u7ea6\u4e0e\u5f02\u5e38\u8fb9\u754c\u3002")
            for position, (title, summary, exercise_title, prompt, requirements) in enumerate(lesson_specs, start=1):
                lesson = Lesson(id=new_id(), course=course, title=title, position=position, markdown_path="content/lessons/java-reference.md", summary=summary)
                lesson.exercises.append(Exercise(id=new_id(), title=exercise_title, position=1, prompt=prompt, requirements=requirements))
            db.add(plan)
            db.flush()
            item = self._ensure_plan_course_item(db, plan, course)
            schedule = CourseScheduleItem(id=new_id(), plan_course_item_id=item.id, scheduled_date=target_date, position=1, start_time=time(9, 0), end_time=time(10, 30))
            task.course_schedule_item_id = schedule.id
            db.add(schedule)
            self._event(db, "SYSTEM_JOB", "course", course.id, "SEED_DEMO", "\u521b\u5efa\u591a\u77e5\u8bc6\u70b9\u6f14\u793a\u8bfe\u7a0b\u95ed\u73af")
            return {"created": True, "plan_line_id": plan.id, "task_id": task.id, "course_id": course.id, "exercise_id": course.lessons[0].exercises[0].id}

    def _latest_attempts(self, db: Session, exercise_ids: list[str], include_drafts: bool = False) -> dict[str, Submission]:
        if not exercise_ids:
            return {}
        query = select(Submission).where(Submission.exercise_id.in_(exercise_ids))
        if not include_drafts:
            query = query.where(Submission.status != "DRAFT")
        rows = db.scalars(query.order_by(Submission.attempt_number, Submission.created_at)).all()
        latest: dict[str, Submission] = {}
        for row in rows:
            current = latest.get(row.exercise_id)
            if current is None or (row.attempt_number, row.created_at or datetime.min) >= (current.attempt_number, current.created_at or datetime.min):
                latest[row.exercise_id] = row
        return latest

    def _annotate_course(self, course: Course, item: PlanCourseItem | None, schedule: CourseScheduleItem | None, total: int, latest: dict[str, Submission]) -> None:
        exercises = [exercise for lesson in course.lessons for exercise in lesson.exercises]
        completed = sum(1 for exercise in exercises if latest.get(exercise.id) and latest[exercise.id].status in PASSED_STATES)
        knowledge_completed = 0
        for lesson in course.lessons:
            lesson_exercises = list(lesson.exercises)
            done = bool(lesson_exercises) and all(latest.get(exercise.id) and latest[exercise.id].status in PASSED_STATES for exercise in lesson_exercises)
            if done:
                knowledge_completed += 1
            setattr(lesson, "progress_state", "DONE" if done else "TODO")
        setattr(course, "planned_start", item.planned_start if item else None)
        setattr(course, "planned_end", item.planned_end if item else None)
        setattr(course, "plan_sequence", item.sequence_number if item else None)
        setattr(course, "plan_total", total)
        setattr(course, "schedule_item", schedule)
        setattr(course, "knowledge_total", len(course.lessons))
        setattr(course, "knowledge_completed", knowledge_completed)
        setattr(course, "exercise_total", len(exercises))
        setattr(course, "exercise_completed", completed)
        setattr(course, "progress_percent", round(completed / len(exercises) * 100) if exercises else 0)

    def _queue_submissions(self, db: Session, plan_line_id: str | None = None) -> list[Submission]:
        query = select(Submission).options(
            joinedload(Submission.exercise).joinedload(Exercise.lesson).joinedload(Lesson.course),
            selectinload(Submission.reviews),
            selectinload(Submission.parent_submission),
            selectinload(Submission.child_submissions),
        ).where(Submission.status.in_(QUEUE_STATUSES)).order_by(Submission.created_at)
        if plan_line_id:
            query = query.join(Submission.exercise).join(Exercise.lesson).join(Lesson.course).where(Course.plan_line_id == plan_line_id)
        rows = db.scalars(query).unique().all()
        # 只把当前作答链的叶子节点交给 Agent；父作答的修正/复测已创建后不再重复进入队列。
        return [row for row in rows if not row.child_submissions]

    def _decorate_queue(self, submissions: list[Submission]) -> list[Submission]:
        labels = {
            "WAITING_REVIEW": ("WAITING_REVIEW", "等待批改"),
            "NEEDS_REVISION": ("REVISION_REQUIRED", "需要修正"),
            "RETEST_REQUIRED": ("RETEST_REQUIRED", "等待复测"),
        }
        for submission in submissions:
            kind, label = labels.get(submission.status, (submission.status, submission.status))
            setattr(submission, "queue_kind", kind)
            setattr(submission, "queue_label", label)
        return submissions

    def agent_queue(self, plan_line_id: str | None = None) -> dict[str, list[dict]]:
        with self.session() as db:
            rows = self._decorate_queue(self._queue_submissions(db, plan_line_id))
            items = [{
                "id": row.id,
                "kind": row.queue_kind,
                "label": row.queue_label,
                "status": row.status,
                "exercise_id": row.exercise_id,
                "exercise_title": row.exercise.title,
                "course_id": row.exercise.lesson.course.id,
                "course_title": row.exercise.lesson.course.title,
                "lesson_id": row.exercise.lesson.id,
                "lesson_title": row.exercise.lesson.title,
                "markdown_path": row.exercise.lesson.markdown_path,
                "plan_line_id": row.exercise.lesson.course.plan_line_id,
                "plan_line": row.exercise.lesson.course.plan_line.name if row.exercise.lesson.course.plan_line else None,
                "parent_submission_id": row.parent_submission_id,
                "attempt_number": row.attempt_number,
                "attempt_kind": row.attempt_kind,
                "source": row.source,
                "answer_text": row.answer_text,
                "review_count": len(row.reviews),
                "next_action": row.next_action or "请外部 Agent 处理该作答。",
                "context": {"submission_id": row.id, "course_id": row.exercise.lesson.course.id, "lesson_id": row.exercise.lesson.id, "markdown_path": row.exercise.lesson.markdown_path},
            } for row in rows]
            return {
                "waiting_review": [item for item in items if item["status"] == "WAITING_REVIEW"],
                "needs_revision": [item for item in items if item["status"] == "NEEDS_REVISION"],
                "waiting_retest": [item for item in items if item["status"] == "RETEST_REQUIRED"],
                "items": items,
            }

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
            latest = self._latest_attempts(db, exercise_ids)
            courses: list[Course] = []
            seen: set[str] = set()
            for schedule in schedules:
                course = schedule.plan_course_item.course
                if course.id not in seen:
                    self._annotate_course(course, by_course.get(course.id), schedule, total_by_plan.get(schedule.plan_course_item.plan_line_id, 0), latest)
                    courses.append(course)
                    seen.add(course.id)
            for item in plan_items:
                if item.course.id not in seen:
                    self._annotate_course(item.course, item, None, total_by_plan.get(item.plan_line_id, 0), latest)
                    courses.append(item.course)
                    seen.add(item.course.id)

            pending = self._decorate_queue(self._queue_submissions(db, plan_line_id))
            plans = db.scalars(select(PlanLine).where(PlanLine.status == "ACTIVE").order_by(PlanLine.priority, PlanLine.name)).all()
            queue = {
                "waiting_review": [x for x in pending if x.status == "WAITING_REVIEW"],
                "needs_revision": [x for x in pending if x.status == "NEEDS_REVISION"],
                "waiting_retest": [x for x in pending if x.status == "RETEST_REQUIRED"],
                "items": pending,
            }
            current_course = next((course for course in courses if course.exercise_total == 0 or course.exercise_completed < course.exercise_total), courses[0] if courses else None)
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

    def get_course(self, course_id: str) -> Course | None:
        with self.session() as db:
            course = db.scalar(select(Course).options(joinedload(Course.plan_line), joinedload(Course.lessons).joinedload(Lesson.exercises)).where(Course.id == course_id))
            if course:
                item = db.scalar(select(PlanCourseItem).where(PlanCourseItem.course_id == course.id).order_by(PlanCourseItem.sequence_number))
                total = db.scalar(select(func.count(PlanCourseItem.id)).where(PlanCourseItem.plan_line_id == item.plan_line_id)) if item else 0
                exercise_ids = [exercise.id for lesson in course.lessons for exercise in lesson.exercises]
                latest = self._latest_attempts(db, exercise_ids)
                drafts = db.scalars(select(Submission).where(Submission.exercise_id.in_(exercise_ids), Submission.status == "DRAFT").order_by(Submission.updated_at, Submission.id)).all()
                drafts_by_exercise = {draft.exercise_id: draft for draft in drafts}
                self._annotate_course(course, item, None, int(total or 0), latest)
                from .markdown import inspect_document
                progress_rows = db.scalars(select(LearningProgress).where(LearningProgress.course_id == course.id)).all()
                progress_by_lesson = {row.lesson_id: row for row in progress_rows}
                for lesson in course.lessons:
                    inspection = inspect_document(self.settings.workspace_root, lesson.markdown_path, render=True)
                    lesson.rendered_html = inspection.html
                    lesson.document_status = inspection.status
                    lesson.learning_progress = progress_by_lesson.get(lesson.id)
                    for exercise in lesson.exercises:
                        exercise.latest_submission = latest.get(exercise.id)
                        exercise.draft = drafts_by_exercise.get(exercise.id)
            return course

    def plan_detail(self, identifier: str, target_date: date | None = None) -> dict:
        detail = self.get_plan_detail(identifier, target_date)
        if detail is None:
            raise DomainError("OBJECT_NOT_FOUND", "学习计划不存在。", "先读取 plan.list 确认计划 ID。")
        return {"plan": {key: value for key, value in detail.items() if key not in {"courses", "current_course", "target_date"}},
                "target_date": detail["target_date"],
                "current_course": course_summary(detail["current_course"]) if detail["current_course"] else None,
                "courses": [course_summary(course) for course in detail.get("courses", [])],
                "next_action": "按课程序号进入当前课程。"}

    def course_detail(self, course_id: str) -> dict:
        row = self.get_course(course_id)
        if row is None:
            raise DomainError("OBJECT_NOT_FOUND", "课程不存在。", "先读取课程列表确认课程 ID。")
        return course_detail(row)

    def course_answer_sheet(self, course_id: str) -> dict:
        from .course_answers import read_answer_sheet
        return read_answer_sheet(self, course_id)

    def write_course_answers(self, course_id: str, answers, operation: str, idempotency_key: str,
                             source: str = "USER_WEB") -> dict:
        from .course_answers import write_answers
        return write_answers(self, course_id, answers, operation, idempotency_key, source)

    def submission_detail(self, submission_id: str) -> dict:
        row = self.get_submission(submission_id)
        if row is None:
            raise DomainError("OBJECT_NOT_FOUND", "作答记录不存在。", "先读取队列或课程详情确认作答 ID。")
        return submission_detail(row)

    def get_submission(self, submission_id: str) -> Submission | None:
        with self.session() as db:
            return db.scalar(select(Submission).options(
                joinedload(Submission.exercise).joinedload(Exercise.lesson).joinedload(Lesson.course),
                selectinload(Submission.reviews),
                selectinload(Submission.parent_submission),
                selectinload(Submission.child_submissions),
            ).where(Submission.id == submission_id))

    def submit_answer(self, exercise_id: str, answer_text: str, task_id: str | None = None, idempotency_key: str | None = None, source: str = "USER_WEB") -> Submission:
        if not answer_text.strip():
            raise DomainError("INVALID_ARGUMENT", "答案不能为空")
        with self.session() as db:
            if idempotency_key:
                existing = db.scalar(select(Submission).where(Submission.idempotency_key == idempotency_key))
                if existing:
                    return existing
            exercise = db.get(Exercise, exercise_id)
            if not exercise:
                raise DomainError("OBJECT_NOT_FOUND", "练习不存在")
            submission = Submission(id=new_id(), exercise_id=exercise_id, task_id=task_id, answer_text=answer_text.strip(), status="WAITING_REVIEW", source=source, idempotency_key=idempotency_key, attempt_number=1, attempt_kind="FIRST", next_action="等待外部 Agent 批改")
            db.add(submission)
            if task_id:
                task = db.get(Task, task_id)
                if task and task.status == "TODO":
                    validate_task_transition(task.status, "IN_PROGRESS")
                    task.status = "IN_PROGRESS"
            db.flush()
            self._event(db, source, "submission", submission.id, "SUBMIT", "用户提交答案，等待外部 Agent 批改")
            return submission

    def _create_followup_submission(self, parent_submission_id: str, answer_text: str, kind: str, idempotency_key: str | None, source: str) -> Submission:
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise DomainError("INVALID_ARGUMENT", "修正或复测答案不能为空", "填写答案后再提交后续版本。")
        answer_text = answer_text.strip()
        with self.session() as db:
            if idempotency_key:
                if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
                    raise DomainError("INVALID_ARGUMENT", "幂等键必须是 1—160 字符的非空文本。", "为本次修正或复测生成稳定幂等键。")
                existing = db.scalar(select(Submission).where(Submission.idempotency_key == idempotency_key))
                if existing:
                    if (existing.parent_submission_id != parent_submission_id or existing.attempt_kind != kind
                            or existing.answer_text != answer_text):
                        raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他父作答、操作类型或答案。", "仅对同一修正/复测请求重试使用原幂等键。")
                    return existing
            parent = db.get(Submission, parent_submission_id)
            if not parent:
                raise DomainError("OBJECT_NOT_FOUND", "父作答记录不存在", "先读取 submission.get 确认父作答 ID。")
            if parent.status not in FOLLOWUP_ALLOWED_STATUSES:
                label = "修正版" if kind == "REVISION" else "复测版"
                raise DomainError("INVALID_ATTEMPT_SOURCE", f"当前状态 {parent.status} 不能创建{label}。", "请先完成批改；等待批改中的作答不能直接进入修正或复测。")
            submission = Submission(
                id=new_id(), exercise_id=parent.exercise_id, task_id=parent.task_id,
                parent_submission_id=parent.id, answer_text=answer_text, status="WAITING_REVIEW",
                source=source, idempotency_key=idempotency_key, attempt_number=parent.attempt_number + 1,
                attempt_kind=kind, next_action="等待外部 Agent 批改",
            )
            db.add(submission)
            db.flush()
            label = "修正版" if kind == "REVISION" else "复测版"
            self._event(db, source, "submission", submission.id, "SUBMIT", f"创建{label}，父作答 {parent.id}")
            return submission
    def revise_submission(self, parent_submission_id: str, answer_text: str, idempotency_key: str | None = None, source: str = "USER_WEB") -> Submission:
        return self._create_followup_submission(parent_submission_id, answer_text, "REVISION", idempotency_key, source)

    def retest_submission(self, parent_submission_id: str, answer_text: str, idempotency_key: str | None = None, source: str = "USER_WEB") -> Submission:
        return self._create_followup_submission(parent_submission_id, answer_text, "RETEST", idempotency_key, source)

    def list_pending_submissions(self) -> list[Submission]:
        with self.session() as db:
            return db.scalars(select(Submission).options(joinedload(Submission.exercise), joinedload(Submission.reviews)).where(Submission.status == "WAITING_REVIEW").order_by(Submission.created_at)).all()

    def write_review(self, submission_id: str, summary: str, detail_markdown: str = "", issue_count: int = 0, needs_revision: bool = False, idempotency_key: str | None = None, source: str = AGENT_SOURCE, *, decision: str | None = None, next_action: str = "") -> ReviewFeedback:
        if not isinstance(summary, str) or not summary.strip():
            raise DomainError("INVALID_ARGUMENT", "批改摘要不能为空", "传入可读的批改摘要。")
        if not isinstance(detail_markdown, str):
            raise DomainError("INVALID_ARGUMENT", "批改详情必须是文本。", "传入 Markdown 文本或省略详情。")
        normalized = normalize_review_decision(decision, needs_revision)
        if decision is not None and decision.strip():
            target = {"PASSED": "PASSED", "REVISION_REQUIRED": "NEEDS_REVISION", "RETEST_REQUIRED": "RETEST_REQUIRED"}[normalized]
        else:
            # 保留旧调用方约定：未传 decision 时，旧命令仍得到 REVIEWED。
            target = "NEEDS_REVISION" if needs_revision else "REVIEWED"
        summary = summary.strip()
        detail_markdown = detail_markdown.strip()
        if not next_action.strip():
            next_action = {"PASSED": "保留通过证据，进入下一个知识点。", "REVISION_REQUIRED": "按批改反馈提交修正版。", "RETEST_REQUIRED": "复习错误点后提交复测版。"}[normalized]
        next_action = next_action.strip()
        with self.session() as db:
            if idempotency_key:
                if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
                    raise DomainError("INVALID_ARGUMENT", "幂等键必须是 1—160 字符的非空文本。", "为本次批改生成稳定幂等键。")
                existing = db.scalar(select(ReviewFeedback).where(ReviewFeedback.idempotency_key == idempotency_key))
                if existing:
                    if (existing.submission_id != submission_id or existing.summary != summary
                            or existing.detail_markdown != detail_markdown or existing.issue_count != issue_count
                            or existing.decision != normalized or existing.next_action != next_action):
                        raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他批改内容。", "仅对同一批改请求重试使用原幂等键。")
                    return existing
            submission = db.get(Submission, submission_id)
            if not submission:
                raise DomainError("OBJECT_NOT_FOUND", "作答记录不存在", "先从 assignment.queue 读取有效作答 ID。")
            if submission.status != "WAITING_REVIEW":
                raise DomainError("INVALID_REVIEW_SOURCE", f"当前作答状态 {submission.status} 不在待批改队列中。", "只对 assignment.queue 返回的作答写入批改。")
            validate_submission_status(submission.status, target)
            review = ReviewFeedback(id=new_id(), submission_id=submission.id, summary=summary, detail_markdown=detail_markdown, issue_count=issue_count, needs_revision=normalized != "PASSED", decision=normalized, next_action=next_action, source=source, idempotency_key=idempotency_key)
            db.add(review)
            submission.status = target
            submission.next_action = next_action
            submission.version += 1
            db.flush()
            self._event(db, source, "submission", submission.id, "REVIEW", f"{normalized}: {summary}")
            return review
    def update_task_status(self, task_id: str, target: str, reason: str = "", next_action: str = "") -> Task:
        with self.session() as db:
            task = db.get(Task, task_id)
            if not task:
                raise DomainError("OBJECT_NOT_FOUND", "任务不存在")
            validate_task_transition(task.status, target, reason, next_action)
            task.status, task.reason, task.next_action = target, reason, next_action
            self._event(db, "USER_WEB", "task", task.id, "STATUS", f"{task.status} → {target}")
            return task

    def check_document(self, relative_path: str) -> Document:
        with self.session() as db:
            inspection = inspect_document(self.settings.workspace_root, relative_path)
            document = db.scalar(select(Document).where(Document.relative_path == relative_path))
            if not document:
                document = Document(id=new_id(), relative_path=relative_path)
                db.add(document)
            document.status = inspection.status
            document.file_size = inspection.file_size
            document.modified_at = inspection.modified_at
            document.content_hash = inspection.content_hash
            return document

    def list_documents(self) -> list[Document]:
        with self.session() as db:
            return db.scalars(select(Document).order_by(Document.status, Document.relative_path)).all()


    def read_document(self, relative_path: str, render: bool = True) -> dict:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise DomainError("INVALID_ARGUMENT", "document.read 需要相对路径。", "传入工作区内 Markdown 文件的相对路径。")
        raw_path = Path(relative_path)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise DomainError("PATH_OUTSIDE_WORKSPACE", "文档路径必须是工作区内不含上级跳转的相对路径。", "改用工作区内 Markdown 文件的相对路径。")
        if raw_path.suffix.lower() not in {".md", ".markdown"}:
            raise DomainError("UNSUPPORTED_DOCUMENT_TYPE", "文档读取目前只接受 Markdown 文件。", "使用 .md 或 .markdown 文件。")
        normalized = raw_path.as_posix()
        candidate = safe_resolve(self.settings.workspace_root, normalized)
        inspection = inspect_document(self.settings.workspace_root, normalized, render=render)
        if inspection.status == "MISSING":
            raise DomainError("DOCUMENT_NOT_FOUND", f"Markdown 文件不存在：{normalized}", "确认相对路径后重试。")
        if inspection.status != "PRESENT":
            raise DomainError("DOCUMENT_UNREADABLE", f"Markdown 文件无法读取：{normalized}", "确认文件使用 UTF-8 编码且当前用户有读取权限。")
        try:
            markdown_text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DomainError("DOCUMENT_UNREADABLE", f"Markdown 文件无法读取：{normalized}", "确认文件使用 UTF-8 编码且当前用户有读取权限。") from exc
        return {
            "path": inspection.relative_path,
            "status": inspection.status,
            "markdown": markdown_text,
            "html": inspection.html,
            "file_size": inspection.file_size,
            "modified_at": inspection.modified_at,
            "content_hash": inspection.content_hash,
        }

    def _replay_submission_write(self, db: Session, key: str | None, operation: str, exercise_id: str | None = None, submission_id: str | None = None) -> Submission | None:
        if not key:
            return None
        if not isinstance(key, str) or len(key) > 160 or not key.strip():
            raise DomainError("INVALID_ARGUMENT", "幂等键必须是 1—160 字符的非空文本。", "为本次操作生成稳定幂等键。")
        receipt = db.scalar(select(SubmissionWriteReceipt).where(SubmissionWriteReceipt.idempotency_key == key))
        if receipt:
            row = db.get(Submission, receipt.submission_id)
            if receipt.operation != operation or (exercise_id and row.exercise_id != exercise_id) or (submission_id and row.id != submission_id):
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他操作或作答。", "仅对同一操作重试使用原幂等键。")
            return row
        return None

    def _record_submission_write(self, db: Session, key: str | None, operation: str, row: Submission) -> None:
        if key:
            db.add(SubmissionWriteReceipt(id=new_id(), idempotency_key=key, operation=operation, submission_id=row.id))
            db.flush()

    def _check_task(self, db: Session, task_id: str | None) -> Task | None:
        task = db.get(Task, task_id) if task_id else None
        if task_id and task is None:
            raise DomainError("OBJECT_NOT_FOUND", "任务不存在。", "先读取今日任务确认 task_id。")
        return task

    def save_submission_draft(self, exercise_id: str, answer_text: str = "", submission_id: str | None = None,
                              task_id: str | None = None, idempotency_key: str | None = None,
                              source: str = "USER_WEB", expected_version: int | None = None) -> Submission:
        if not isinstance(answer_text, str):
            raise DomainError("INVALID_ARGUMENT", "答案草稿必须是文本。", "传入 answer_text 字符串。")
        with self.session() as db:
            replay = self._replay_submission_write(db, idempotency_key, "DRAFT_SAVE", exercise_id, submission_id)
            if replay:
                return replay
            if not db.get(Exercise, exercise_id):
                raise DomainError("OBJECT_NOT_FOUND", "练习不存在。", "先读取课程详情确认 exercise_id。")
            self._check_task(db, task_id)
            row = db.get(Submission, submission_id) if submission_id else db.scalar(
                select(Submission).where(Submission.exercise_id == exercise_id, Submission.task_id == task_id,
                                         Submission.status == "DRAFT").order_by(Submission.created_at.desc()))
            if submission_id and row is None:
                raise DomainError("OBJECT_NOT_FOUND", "草稿不存在。", "重新读取作答状态。")
            if row:
                if row.exercise_id != exercise_id:
                    raise DomainError("INVALID_ARGUMENT", "草稿与练习不匹配。", "使用该草稿的 exercise_id。")
                if row.status != "DRAFT":
                    raise DomainError("INVALID_STATE_TRANSITION", "正式作答不可覆盖。", "按批改反馈创建修正版或复测版。")
                if expected_version is not None and expected_version != row.version:
                    raise DomainError("VERSION_CONFLICT", "草稿已被另一窗口更新。", "重新读取草稿并确认内容后再保存。")
                row.answer_text = answer_text
                row.version += 1
                row.source = source
            else:
                attempt = (db.scalar(select(func.max(Submission.attempt_number)).where(Submission.exercise_id == exercise_id)) or 0) + 1
                row = Submission(id=new_id(), exercise_id=exercise_id, task_id=task_id, answer_text=answer_text,
                                 status="DRAFT", source=source, attempt_number=attempt, attempt_kind="FIRST",
                                 next_action="继续编辑草稿，完成后正式提交。")
                db.add(row)
            db.flush()
            self._record_submission_write(db, idempotency_key, "DRAFT_SAVE", row)
            self._event(db, source, "submission", row.id, "DRAFT_SAVE", f"保存草稿 v{row.version}")
            return row

    def submit_submission(self, exercise_id: str | None = None, answer_text: str | None = None,
                          submission_id: str | None = None, task_id: str | None = None,
                          idempotency_key: str | None = None, source: str = "USER_WEB",
                          expected_version: int | None = None) -> Submission:
        if answer_text is not None and not isinstance(answer_text, str):
            raise DomainError("INVALID_ARGUMENT", "答案必须是文本。", "传入 answer_text 字符串。")
        with self.session() as db:
            replay = self._replay_submission_write(db, idempotency_key, "SUBMIT", exercise_id, submission_id)
            if replay:
                return replay
            self._check_task(db, task_id)
            row = db.get(Submission, submission_id) if submission_id else None
            if submission_id:
                if row is None:
                    raise DomainError("OBJECT_NOT_FOUND", "作答记录不存在。", "先保存或读取草稿。")
                if row.status != "DRAFT":
                    raise DomainError("INVALID_STATE_TRANSITION", "只有草稿可以正式提交。", "已提交作答只读；按批改创建后续版本。")
                if exercise_id and exercise_id != row.exercise_id:
                    raise DomainError("INVALID_ARGUMENT", "草稿与练习不匹配。", "使用该草稿所属练习。")
                if expected_version is not None and expected_version != row.version:
                    raise DomainError("VERSION_CONFLICT", "草稿版本已发生变化。", "重新读取草稿再提交。")
                if answer_text is not None:
                    row.answer_text = answer_text
                if not row.answer_text.strip():
                    raise DomainError("INVALID_ARGUMENT", "答案不能为空。", "完成答案后再正式提交。")
                row.version += 1
            else:
                if not exercise_id:
                    raise DomainError("INVALID_ARGUMENT", "需要 exercise_id 或 submission_id。", "提交已有草稿或提供练习 ID 和答案。")
                if not db.get(Exercise, exercise_id):
                    raise DomainError("OBJECT_NOT_FOUND", "练习不存在。", "先读取课程详情确认练习 ID。")
                if not answer_text or not answer_text.strip():
                    raise DomainError("INVALID_ARGUMENT", "答案不能为空。", "完成答案后再正式提交。")
                attempt = (db.scalar(select(func.max(Submission.attempt_number)).where(Submission.exercise_id == exercise_id)) or 0) + 1
                row = Submission(id=new_id(), exercise_id=exercise_id, task_id=task_id, answer_text=answer_text.strip(),
                                 source=source, attempt_number=attempt, attempt_kind="FIRST")
                db.add(row)
            row.status = "WAITING_REVIEW"
            row.next_action = "等待外部 Agent 批改"
            row.source = source
            task = self._check_task(db, row.task_id)
            if task and task.status == "TODO":
                validate_task_transition(task.status, "IN_PROGRESS")
                task.status = "IN_PROGRESS"
            db.flush()
            self._record_submission_write(db, idempotency_key, "SUBMIT", row)
            self._event(db, source, "submission", row.id, "SUBMIT", "正式提交，等待外部 Agent 批改")
            return row

    def save_learning_progress(
        self,
        course_id: str,
        lesson_id: str,
        progress_percent: int,
        last_position: str = "",
        source: str = "USER_ENGINE",
    ) -> LearningProgress:
        if isinstance(progress_percent, bool) or not isinstance(progress_percent, int) or not 0 <= progress_percent <= 100:
            raise DomainError("INVALID_ARGUMENT", "progress_percent 必须是 0 到 100 的整数。", "传入有效的阅读进度百分比。")
        if not isinstance(last_position, str):
            raise DomainError("INVALID_ARGUMENT", "last_position 必须是文本。", "传入阅读位置字符串或省略该字段。")
        with self.session() as db:
            course = db.get(Course, course_id)
            lesson = db.get(Lesson, lesson_id)
            if not course or not lesson:
                raise DomainError("OBJECT_NOT_FOUND", "课程或知识点不存在。", "先读取 course.detail 确认 ID。")
            if lesson.course_id != course.id:
                raise DomainError("INVALID_ARGUMENT", "知识点不属于指定课程。", "使用该课程下的 lesson_id。")
            status = "COMPLETED" if progress_percent == 100 else "NOT_STARTED" if progress_percent == 0 else "IN_PROGRESS"
            progress = db.scalar(select(LearningProgress).where(LearningProgress.course_id == course_id, LearningProgress.lesson_id == lesson_id))
            if progress:
                progress.progress_percent = progress_percent
                progress.status = status
                progress.last_position = (last_position or "")[:500]
                progress.source = source
            else:
                progress = LearningProgress(
                    id=new_id(), course_id=course_id, lesson_id=lesson_id,
                    progress_percent=progress_percent, status=status,
                    last_position=(last_position or "")[:500], source=source,
                )
                db.add(progress)
            db.flush()
            return progress

    def generate_snapshot(self, target_date: date | None = None, scope: str = "today") -> ContextSnapshot:
        target_date = target_date or date.today()
        dashboard = self.dashboard(target_date)
        lines = [f"# StudyFlow 上下文快照 · {target_date}", "", f"- 当前范围：{scope}", f"- 主任务：{dashboard['primary_task'].title if dashboard['primary_task'] else '暂无'}", f"- 待批改：{len(dashboard['pending'])}", "", "## 下一动作", "打开今日工作台，继续主任务。"]
        relative_path = f"content/snapshots/{target_date}-snapshot.md"
        file_path = self.settings.workspace_root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.session() as db:
            snapshot = ContextSnapshot(id=new_id(), snapshot_date=target_date, scope=scope, relative_path=relative_path, current_pointer=dashboard["primary_task"].title if dashboard["primary_task"] else "", summary="\n".join(lines))
            db.add(snapshot)
            db.flush()
            self._event(db, AGENT_SOURCE, "snapshot", snapshot.id, "GENERATE", "生成上下文快照")
            return snapshot

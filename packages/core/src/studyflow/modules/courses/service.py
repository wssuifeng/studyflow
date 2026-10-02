from __future__ import annotations
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from studyflow.modules.courses.presentation import course_detail
from studyflow.shared.domain import COURSE_CONTENT_TYPES, DOCUMENT_TYPES, EXERCISE_TYPES, DomainError
from studyflow.infrastructure.markdown import inspect_document, parse_front_matter, resolve_import_path, validate_import_metadata
from studyflow.modules.courses.models import Course, Exercise, Lesson
from studyflow.modules.documents.models import Document
from studyflow.modules.learning.models import LearningProgress, Submission
from studyflow.modules.planning.models import PlanCourseItem, PlanLine
from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE
from studyflow.modules.planning.repository import ensure_course_membership
from studyflow.modules.learning.repository import latest_attempts, annotate_course


from studyflow.infrastructure.runtime import Runtime, Service


class CoursesService(Service):
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
                        ensure_course_membership(db, plan, course)
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
            plan_course_item = ensure_course_membership(db, plan, course)
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

    def get_course(self, course_id: str) -> Course | None:
        with self.session() as db:
            course = db.scalar(select(Course).options(joinedload(Course.plan_line), joinedload(Course.lessons).joinedload(Lesson.exercises)).where(Course.id == course_id))
            if course:
                item = db.scalar(select(PlanCourseItem).where(PlanCourseItem.course_id == course.id).order_by(PlanCourseItem.sequence_number))
                total = db.scalar(select(func.count(PlanCourseItem.id)).where(PlanCourseItem.plan_line_id == item.plan_line_id)) if item else 0
                exercise_ids = [exercise.id for lesson in course.lessons for exercise in lesson.exercises]
                latest = latest_attempts(db, exercise_ids)
                drafts = db.scalars(select(Submission).where(Submission.exercise_id.in_(exercise_ids), Submission.status == "DRAFT").order_by(Submission.updated_at, Submission.id)).all()
                drafts_by_exercise = {draft.exercise_id: draft for draft in drafts}
                annotate_course(course, item, None, int(total or 0), latest)
                from studyflow.markdown import inspect_document
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

    def course_detail(self, course_id: str) -> dict:
        row = self.get_course(course_id)
        if row is None:
            raise DomainError("OBJECT_NOT_FOUND", "课程不存在。", "先读取课程列表确认课程 ID。")
        return course_detail(row)

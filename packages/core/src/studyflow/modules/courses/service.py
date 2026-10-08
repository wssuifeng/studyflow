from __future__ import annotations
from pathlib import Path
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import joinedload
from studyflow.modules.courses.presentation import course_detail
from studyflow.shared.domain import COURSE_CONTENT_TYPES, DOCUMENT_TYPES, EXERCISE_TYPES, DomainError
from studyflow.infrastructure.markdown import inspect_document, parse_front_matter, resolve_import_path, validate_import_metadata
from studyflow.modules.courses.models import Course, CourseRevision, Exercise, Lesson
from studyflow.modules.documents.models import Document
from studyflow.modules.learning.models import (CourseStudySession, CourseWriteReceipt, LearningProgress,
    StudyNote, StudyNoteReceipt, Submission, SubmissionChainLink, SubmissionWriteReceipt)
from studyflow.modules.planning.models import CourseScheduleItem, PlanCourseItem, PlanLine, Task, TimeBlock
from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE
from studyflow.modules.reviews.models import RetestTask, ReviewFeedback
from studyflow.modules.planning.repository import ensure_course_membership
from studyflow.modules.learning.repository import latest_attempts, annotate_course


from studyflow.infrastructure.runtime import Runtime, Service


class CoursesService(Service):
    def list_courses(self, plan_line_id: str | None = None) -> list[Course]:
        with self.session() as db:
            if plan_line_id:
                query = select(Course).join(PlanCourseItem, PlanCourseItem.course_id == Course.id).options(joinedload(Course.plan_line), joinedload(Course.lessons.and_(Lesson.included == True)).joinedload(Lesson.exercises.and_(Exercise.included == True))).where(Course.status == "ACTIVE", PlanCourseItem.plan_line_id == plan_line_id).order_by(PlanCourseItem.sequence_number, Course.title)
            else:
                query = select(Course).options(joinedload(Course.plan_line), joinedload(Course.lessons.and_(Lesson.included == True)).joinedload(Lesson.exercises.and_(Exercise.included == True))).where(Course.status == "ACTIVE").order_by(Course.title)
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
            course = db.scalar(select(Course).options(joinedload(Course.plan_line), joinedload(Course.lessons.and_(Lesson.included == True)).joinedload(Lesson.exercises.and_(Exercise.included == True))).where(Course.id == course_id))
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
                    lesson.content_blocks = []
                    if inspection.status == "PRESENT":
                        from .content import render_blocks
                        from studyflow.infrastructure.markdown import safe_resolve
                        lesson.content_blocks = render_blocks(safe_resolve(self.settings.workspace_root, lesson.markdown_path).read_text(encoding="utf-8"), [e.id for e in lesson.exercises])
                    lesson.document_status = inspection.status
                    lesson.learning_progress = progress_by_lesson.get(lesson.id)
                    for exercise in lesson.exercises:
                        exercise.latest_submission = latest.get(exercise.id)
                        exercise.draft = drafts_by_exercise.get(exercise.id)
            return course

    def preview_course_purge(self, course_ids: list[str] | None = None) -> dict:
        """Return a safe, read-only inventory for deleting all course-owned data.

        The operation intentionally lives in the courses module so the CLI cannot
        invent a second deletion path. It never touches the database or files.
        """
        with self.session(read_only=True) as db:
            return self._course_purge_inventory(db, course_ids)

    def purge_courses(self, confirm: bool = False, course_ids: list[str] | None = None) -> dict:
        """Delete course-owned data while preserving plan lines and schema.

        This is a destructive maintenance operation. The CLI must require an
        explicit ``--confirm`` and a separately validated consistency backup;
        the service still checks ``confirm`` so other callers cannot bypass the
        guard accidentally.
        """
        if not confirm:
            raise DomainError(
                "CONFIRMATION_REQUIRED",
                "清理课程必须显式确认，未执行任何删除。",
                "先运行 workspace purge-courses --dry-run，再使用 --confirm 和已验证的备份。",
            )
        paths: list[Path] = []
        with self.session() as db:
            inventory = self._course_purge_inventory(db, course_ids)
            if not inventory["course_ids"]:
                return inventory | {"deleted": False, "files_removed": [], "warnings": []}
            course_ids = inventory["course_ids"]
            lesson_ids = inventory["lesson_ids"]
            exercise_ids = inventory["exercise_ids"]
            session_ids = inventory["study_session_ids"]
            submission_ids = inventory["submission_ids"]
            retest_ids = inventory["retest_task_ids"]
            task_ids = inventory["linked_task_ids"]
            schedule_ids = inventory["schedule_item_ids"]
            item_ids = inventory["plan_course_item_ids"]

            # Null the self-reference before deleting the submission set. This
            # keeps SQLite foreign-key enforcement safe even for revision chains.
            if submission_ids:
                db.execute(update(Submission).where(Submission.id.in_(submission_ids)).values(parent_submission_id=None))
                db.execute(delete(ReviewFeedback).where(ReviewFeedback.submission_id.in_(submission_ids)))
                db.execute(delete(SubmissionChainLink).where(or_(SubmissionChainLink.parent_id.in_(submission_ids), SubmissionChainLink.child_id.in_(submission_ids))))
                db.execute(delete(SubmissionWriteReceipt).where(SubmissionWriteReceipt.submission_id.in_(submission_ids)))
            if session_ids:
                db.execute(delete(StudyNote).where(StudyNote.study_session_id.in_(session_ids)))
                db.execute(delete(StudyNoteReceipt).where(StudyNoteReceipt.study_session_id.in_(session_ids)))
            if retest_ids or submission_ids or session_ids:
                predicates = []
                if retest_ids:
                    predicates.append(RetestTask.id.in_(retest_ids))
                if submission_ids:
                    predicates.append(RetestTask.parent_submission_id.in_(submission_ids))
                if session_ids:
                    predicates.append(RetestTask.study_session_id.in_(session_ids))
                db.execute(delete(RetestTask).where(or_(*predicates)))
            if submission_ids:
                db.execute(delete(Submission).where(Submission.id.in_(submission_ids)))
            if course_ids or session_ids:
                predicates = [CourseWriteReceipt.course_id.in_(course_ids)]
                if session_ids:
                    predicates.append(CourseWriteReceipt.study_session_id.in_(session_ids))
                db.execute(delete(CourseWriteReceipt).where(or_(*predicates)))
            if session_ids:
                db.execute(delete(CourseStudySession).where(CourseStudySession.id.in_(session_ids)))
            if course_ids:
                db.execute(delete(LearningProgress).where(LearningProgress.course_id.in_(course_ids)))
                db.execute(delete(CourseRevision).where(CourseRevision.course_id.in_(course_ids)))
            if task_ids:
                # A schedule-linked task belongs to the removed course binding.
                # Clear any unexpected submission reference before removing it;
                # normal course submissions have already been deleted above.
                db.execute(update(Submission).where(Submission.task_id.in_(task_ids)).values(task_id=None))
                db.execute(delete(TimeBlock).where(TimeBlock.task_id.in_(task_ids)))
                db.execute(delete(Task).where(Task.id.in_(task_ids)))
            if schedule_ids:
                db.execute(delete(CourseScheduleItem).where(CourseScheduleItem.id.in_(schedule_ids)))
            if item_ids:
                db.execute(delete(PlanCourseItem).where(PlanCourseItem.id.in_(item_ids)))
            if course_ids:
                db.execute(update(PlanLine).where(PlanLine.focus_course_id.in_(course_ids)).values(focus_course_id=None))
            if inventory["deletable_document_paths"]:
                db.execute(delete(Document).where(Document.relative_path.in_(inventory["deletable_document_paths"])))
            if exercise_ids:
                db.execute(delete(Exercise).where(Exercise.id.in_(exercise_ids)))
            if lesson_ids:
                db.execute(delete(Lesson).where(Lesson.id.in_(lesson_ids)))
            db.execute(delete(Course).where(Course.id.in_(course_ids)))
            self._event(db, AGENT_SOURCE, "workspace", "courses", "PURGE_COURSES", f"清理 {len(course_ids)} 门课程及其课程专属数据")
            paths = [self.settings.workspace_root / relative for relative in inventory["deletable_document_paths"]]
            result = inventory | {"deleted": True, "files_removed": [], "warnings": []}
        for path in paths:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    result["files_removed"].append(path.relative_to(self.settings.workspace_root).as_posix())
            except OSError as exc:
                result["warnings"].append(f"课程文档未能删除：{path}（{exc}）")
        return result

    def _course_purge_inventory(self, db, course_ids: list[str] | None = None) -> dict:
        if course_ids is None:
            courses = db.scalars(select(Course).order_by(Course.created_at, Course.id)).all()
        else:
            requested = list(dict.fromkeys(course_ids))
            courses = db.scalars(select(Course).where(Course.id.in_(requested)).order_by(Course.created_at, Course.id)).all() if requested else []
        course_ids = [row.id for row in courses]
        lessons = db.scalars(select(Lesson).where(Lesson.course_id.in_(course_ids))).all() if course_ids else []
        lesson_ids = [row.id for row in lessons]
        exercises = db.scalars(select(Exercise).where(Exercise.lesson_id.in_(lesson_ids))).all() if lesson_ids else []
        exercise_ids = [row.id for row in exercises]
        sessions = db.scalars(select(CourseStudySession).where(CourseStudySession.course_id.in_(course_ids))).all() if course_ids else []
        session_ids = [row.id for row in sessions]
        submissions = db.scalars(select(Submission).where(Submission.exercise_id.in_(exercise_ids))).all() if exercise_ids else []
        submission_ids = [row.id for row in submissions]
        retest_filter = []
        if submission_ids:
            retest_filter.append(RetestTask.parent_submission_id.in_(submission_ids))
        if session_ids:
            retest_filter.append(RetestTask.study_session_id.in_(session_ids))
        retests = db.scalars(select(RetestTask).where(or_(*retest_filter))).all() if retest_filter else []
        retest_ids = [row.id for row in retests]
        items = db.scalars(select(PlanCourseItem).where(PlanCourseItem.course_id.in_(course_ids))).all() if course_ids else []
        item_ids = [row.id for row in items]
        schedule = db.scalars(select(CourseScheduleItem).where(CourseScheduleItem.plan_course_item_id.in_(item_ids))).all() if item_ids else []
        schedule_ids = [row.id for row in schedule]
        tasks = db.scalars(select(Task).where(Task.course_schedule_item_id.in_(schedule_ids))).all() if schedule_ids else []
        task_ids = [row.id for row in tasks]
        document_paths = sorted({row.markdown_path for row in lessons if row.markdown_path})
        remaining_paths = set()
        if course_ids is not None and course_ids:
            remaining_paths = set(db.scalars(select(Lesson.markdown_path).where(~Lesson.course_id.in_(course_ids))).all())
        protected_document_paths = sorted(path for path in document_paths if path in remaining_paths)
        deletable_document_paths = sorted(path for path in document_paths if path not in remaining_paths)
        review_count = db.scalar(select(func.count(ReviewFeedback.id)).where(ReviewFeedback.submission_id.in_(submission_ids))) if submission_ids else 0
        progress_count = db.scalar(select(func.count(LearningProgress.id)).where(LearningProgress.course_id.in_(course_ids))) if course_ids else 0
        revision_count = db.scalar(select(func.count(CourseRevision.id)).where(CourseRevision.course_id.in_(course_ids))) if course_ids else 0
        return {
            "deleted": False,
            "course_ids": course_ids,
            "course_titles": [row.title for row in courses],
            "lesson_ids": lesson_ids,
            "exercise_ids": exercise_ids,
            "study_session_ids": session_ids,
            "submission_ids": submission_ids,
            "retest_task_ids": retest_ids,
            "plan_course_item_ids": item_ids,
            "schedule_item_ids": schedule_ids,
            "linked_task_ids": task_ids,
            "document_paths": document_paths,
            "deletable_document_paths": deletable_document_paths,
            "protected_document_paths": protected_document_paths,
            "counts": {
                "courses": len(course_ids), "lessons": len(lesson_ids), "exercises": len(exercise_ids),
                "study_sessions": len(session_ids), "submissions": len(submission_ids), "review_feedback": len(submission_ids),
                "retest_tasks": len(retest_ids), "course_revisions": len(course_ids), "learning_progress": len(course_ids),
                "plan_course_items": len(item_ids), "schedule_items": len(schedule_ids), "linked_tasks": len(task_ids),
                "documents": len(deletable_document_paths), "protected_documents": len(protected_document_paths),
            },
        }

    def validate_course_package(self, source_path):
        from .packages import inspect_package
        return inspect_package(source_path)[1]

    def import_course_package(self, source_path):
        from .packages import import_package
        return import_package(self, source_path)

    def course_detail(self, course_id: str) -> dict:
        row = self.get_course(course_id)
        if row is None:
            raise DomainError("OBJECT_NOT_FOUND", "课程不存在。", "先读取课程列表确认课程 ID。")
        return course_detail(row)

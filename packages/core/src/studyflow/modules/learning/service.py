from __future__ import annotations
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload
from studyflow.modules.learning.presentation import submission_detail
from studyflow.shared.domain import DomainError, validate_task_transition
from studyflow.modules.courses.models import Course, Exercise, Lesson
from studyflow.modules.learning.models import LearningProgress, Submission, SubmissionWriteReceipt
from studyflow.modules.planning.models import Task
from studyflow.shared.ids import new_id
from studyflow.shared.constants import FOLLOWUP_ALLOWED_STATUSES
from studyflow.modules.planning.repository import require_task


from studyflow.infrastructure.runtime import Runtime, Service


class LearningService(Service):
    def plan_notebook(self, plan_line_id):
        from studyflow.modules.learning.notebooks import read_notebook
        return read_notebook(self, plan_line_id)

    def save_plan_notebook(self, plan_line_id, blocks, expected_version, idempotency_key, source="USER_WEB"):
        from studyflow.modules.learning.notebooks import save_notebook
        return save_notebook(self, plan_line_id, blocks, expected_version, idempotency_key, source)

    def study_notes(self, study_session_id):
        from .notes import read_notes
        return read_notes(self, study_session_id)

    def save_study_note(self, study_session_id, lesson_id, text, expected_version, idempotency_key, source="USER_WEB"):
        from .notes import save_note
        return save_note(self, study_session_id, lesson_id, text, expected_version, idempotency_key, source)

    def open_course_study(self, course_id, idempotency_key, new_version=False, review_round=False):
        from .study_sessions import open_study
        return open_study(self, course_id, idempotency_key, new_version, review_round)

    def course_study_detail(self, study_session_id):
        from .study_sessions import detail
        return detail(self, study_session_id)

    def save_study_progress(self, study_session_id, lesson_id, progress_percent, last_position="", expected_version=None):
        from .study_sessions import save_progress
        return save_progress(self, study_session_id, lesson_id, progress_percent, last_position, expected_version)

    def complete_course_reading(self, study_session_id):
        from .study_sessions import complete_reading
        return complete_reading(self, study_session_id)

    def course_answer_sheet(self, course_id: str, study_session_id: str | None = None) -> dict:
        from .course_answers import read_answer_sheet
        return read_answer_sheet(self, course_id, study_session_id)

    def write_course_answers(self, course_id: str, answers, operation: str, idempotency_key: str,
                             source: str = "USER_WEB", study_session_id: str | None = None) -> dict:
        from .course_answers import write_answers
        return write_answers(self, course_id, answers, operation, idempotency_key, source, study_session_id)

    def submission_detail(self, submission_id: str) -> dict:
        row = self.get_submission(submission_id)
        if row is None:
            raise DomainError("OBJECT_NOT_FOUND", "作答记录不存在。", "先读取队列或课程详情确认作答 ID。")
        return submission_detail(row)

    def get_submission(self, submission_id: str) -> Submission | None:
        with self.session() as db:
            result = db.scalar(select(Submission).options(
                joinedload(Submission.exercise).joinedload(Exercise.lesson).joinedload(Lesson.course),
                selectinload(Submission.study_session),
                selectinload(Submission.reviews),
                selectinload(Submission.parent_submission).selectinload(Submission.study_session),
                selectinload(Submission.child_submissions),
            ).where(Submission.id == submission_id))
            if result:
                from .study_sessions import current_study
                current=current_study(db,result.exercise.lesson.course_id)
                result.is_current_study=not current or not result.study_session_id and current.revision==1 or result.study_session_id==current.id
            if result and result.retest_task_id:
                from studyflow.modules.reviews.models import RetestTask
                from studyflow.modules.reviews.retests import public_task
                task=db.get(RetestTask,result.retest_task_id)
                result.public_retest=public_task(task) if task else None
            return result

    def submit_answer(self, exercise_id: str, answer_text: str, task_id: str | None = None, idempotency_key: str | None = None, source: str = "USER_WEB") -> Submission:
        return self.submit_submission(exercise_id=exercise_id, answer_text=answer_text, task_id=task_id, idempotency_key=idempotency_key, source=source)

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
            retest_task=None
            if kind=="RETEST":
                from studyflow.modules.reviews.models import RetestTask
                retest_task=db.scalar(select(RetestTask).where(RetestTask.parent_submission_id==parent.id))
                if not retest_task:raise DomainError("RETEST_TASK_REQUIRED","先发布独立冻结复测题，再提交复测答案。","读取assignment.summary中的PUBLISH_RETEST任务。")
            submission = Submission(
                id=new_id(), retest_task_id=retest_task.id if retest_task else parent.retest_task_id, exercise_id=parent.exercise_id, task_id=parent.task_id,
                parent_submission_id=parent.id, study_session_id=parent.study_session_id, answer_text=answer_text, status="WAITING_REVIEW",
                source=source, idempotency_key=idempotency_key, attempt_number=parent.attempt_number + 1,
                attempt_kind=kind, next_action="等待外部 Agent 批改",
            )
            from .write_contract import claim_parent
            claim_parent(db, parent, submission.id, source)
            from .study_sessions import bind_submission
            bind_submission(db,submission,is_new=True)
            db.add(submission)
            db.flush()
            if retest_task:retest_task.status="WAITING_REVIEW"
            label = "修正版" if kind == "REVISION" else "复测版"
            self._event(db, source, "submission", submission.id, "SUBMIT", f"创建{label}，父作答 {parent.id}")
            return submission

    def revise_submission(self, parent_submission_id: str, answer_text: str, idempotency_key: str | None = None, source: str = "USER_WEB") -> Submission:
        return self._create_followup_submission(parent_submission_id, answer_text, "REVISION", idempotency_key, source)

    def retest_submission(self, parent_submission_id: str, answer_text: str, idempotency_key: str | None = None, source: str = "USER_WEB") -> Submission:
        return self._create_followup_submission(parent_submission_id, answer_text, "RETEST", idempotency_key, source)

    def save_submission_draft(self, exercise_id: str, answer_text: str = "", submission_id: str | None = None,
                              task_id: str | None = None, idempotency_key: str | None = None,
                              source: str = "USER_WEB", expected_version: int | None = None) -> Submission:
        if not isinstance(answer_text, str):
            raise DomainError("INVALID_ARGUMENT", "答案草稿必须是文本。", "传入 answer_text 字符串。")
        payload = {"operation": "DRAFT_SAVE", "exercise_id": exercise_id, "submission_id": submission_id, "answer_text": answer_text, "task_id": task_id, "expected_version": expected_version, "source": source}
        from .write_contract import replay, record
        with self.session() as db:
            replayed = replay(db, idempotency_key, "DRAFT_SAVE", payload)
            if replayed:
                return replayed
            if not db.get(Exercise, exercise_id):
                raise DomainError("OBJECT_NOT_FOUND", "练习不存在。", "先读取课程详情确认 exercise_id。")
            require_task(db, task_id)
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
            from .study_sessions import bind_submission
            bind_submission(db,row,is_new=not bool(submission_id))
            db.flush()
            record(db, idempotency_key, "DRAFT_SAVE", payload, row)
            self._event(db, source, "submission", row.id, "DRAFT_SAVE", f"保存草稿 v{row.version}")
            return row

    def submit_submission(self, exercise_id: str | None = None, answer_text: str | None = None,
                          submission_id: str | None = None, task_id: str | None = None,
                          idempotency_key: str | None = None, source: str = "USER_WEB",
                          expected_version: int | None = None) -> Submission:
        if answer_text is not None and not isinstance(answer_text, str):
            raise DomainError("INVALID_ARGUMENT", "答案必须是文本。", "传入 answer_text 字符串。")
        payload = {"operation": "SUBMIT", "exercise_id": exercise_id, "submission_id": submission_id, "answer_text": answer_text, "task_id": task_id, "expected_version": expected_version, "source": source}
        from .write_contract import replay, record
        with self.session() as db:
            replayed = replay(db, idempotency_key, "SUBMIT", payload)
            if replayed:
                return replayed
            require_task(db, task_id)
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
            from .study_sessions import bind_submission
            bind_submission(db,row,is_new=not bool(submission_id))
            row.status = "WAITING_REVIEW"
            row.next_action = "等待外部 Agent 批改"
            row.source = source
            task = require_task(db, row.task_id)
            if task and task.status == "TODO":
                validate_task_transition(task.status, "IN_PROGRESS")
                task.status = "IN_PROGRESS"
            db.flush()
            record(db, idempotency_key, "SUBMIT", payload, row)
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

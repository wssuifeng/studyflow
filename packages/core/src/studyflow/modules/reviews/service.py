from __future__ import annotations
from sqlalchemy import select,update
from sqlalchemy.orm import joinedload
from studyflow.shared.domain import DomainError, normalize_review_decision, validate_submission_status
from studyflow.modules.reviews.models import ReviewFeedback
from studyflow.modules.learning.models import Submission
from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE
from studyflow.modules.reviews.repository import queue_submissions, decorate_queue


from studyflow.infrastructure.runtime import Runtime, Service


class ReviewsService(Service):
    def agent_queue(self, plan_line_id: str | None = None) -> dict[str, list[dict]]:
        with self.session() as db:
            rows = decorate_queue(queue_submissions(db, plan_line_id))
            from studyflow.modules.learning.study_sessions import frozen_context
            items = [{
                "id": row.id,
                "study_session_id": row.study_session_id, "batch_id": row.batch_id,
                "study_context": frozen_context(row),
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
            for item in items:
                context = item["study_context"]
                if context:
                    item.update(exercise_title=context["exercise"]["title"], course_title=context["course"]["title"],
                                lesson_title=context["lesson"]["title"], markdown_path=context["lesson"]["markdown_path"])
                item["snapshot_status"] = "FROZEN" if context else "LEGACY_UNVERSIONED"
            batches = {}
            from studyflow.modules.learning.models import CourseWriteReceipt
            for item in items:
                key = item["batch_id"] or item["id"]
                if key not in batches:
                    receipt = db.get(CourseWriteReceipt, key)
                    written = db.scalars(select(Submission).where(Submission.batch_id == key)).all() if receipt else []
                    batches[key] = {"batch_id":key,"course_id":item["course_id"],"course_title":item["course_title"],
                        "study_session_id":item["study_session_id"],"submission_ids":[],"total_count":len(written) or 1,
                        "reviewed_count":sum(row.status != "WAITING_REVIEW" for row in written)}
                batches[key]["submission_ids"].append(item["id"])
            return {
                "batches": list(batches.values()),
                "waiting_review": [item for item in items if item["status"] == "WAITING_REVIEW"],
                "needs_revision": [item for item in items if item["status"] == "NEEDS_REVISION"],
                "waiting_retest": [item for item in items if item["status"] == "RETEST_REQUIRED"],
                "items": items,
            }

    def list_pending_submissions(self) -> list[Submission]:
        with self.session() as db:
            return db.scalars(select(Submission).options(joinedload(Submission.exercise), joinedload(Submission.reviews)).where(Submission.status == "WAITING_REVIEW").order_by(Submission.created_at)).all()

    def write_review(self, submission_id: str, summary: str, detail_markdown: str = "", issue_count: int = 0, needs_revision: bool = False, idempotency_key: str | None = None, source: str = AGENT_SOURCE, *, decision: str | None = None, next_action: str = "", issues: list | None = None) -> ReviewFeedback:
        if not isinstance(summary, str) or not summary.strip():
            raise DomainError("INVALID_ARGUMENT", "批改摘要不能为空", "传入可读的批改摘要。")
        if not isinstance(detail_markdown, str):
            raise DomainError("INVALID_ARGUMENT", "批改详情必须是文本。", "传入 Markdown 文本或省略详情。")
        import json
        from .retests import validate_issues
        normalized = normalize_review_decision(decision, needs_revision)
        if decision is not None and decision.strip():
            target = {"PASSED": "PASSED", "REVISION_REQUIRED": "NEEDS_REVISION", "RETEST_REQUIRED": "RETEST_REQUIRED"}[normalized]
        else:
            # 保留旧调用方约定：未传 decision 时，旧命令仍得到 REVIEWED。
            target = "NEEDS_REVISION" if needs_revision else "REVIEWED"
        if issues is not None:
            if not isinstance(issues,list): raise DomainError("INVALID_ARGUMENT","issues必须为数组。")
            issue_count=len(issues)
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
                            or existing.decision != normalized or existing.next_action != next_action
                            or issues is not None and existing.issues_json != json.dumps(issues,ensure_ascii=False)):

                        raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他批改内容。", "仅对同一批改请求重试使用原幂等键。")
                    return existing
            submission = db.get(Submission, submission_id)
            if not submission:
                raise DomainError("OBJECT_NOT_FOUND", "作答记录不存在", "先从 assignment.queue 读取有效作答 ID。")
            if submission.status != "WAITING_REVIEW":
                raise DomainError("INVALID_REVIEW_SOURCE", f"当前作答状态 {submission.status} 不在待批改队列中。", "只对 assignment.queue 返回的作答写入批改。")
            validate_issues(submission.answer_text, issues)
            if issues is not None:
                if normalized == "PASSED" and issues: raise DomainError("INVALID_ARGUMENT", "通过反馈不能标注待改错误。")
                issue_count = len(issues)
            validate_submission_status(submission.status, target)
            review = ReviewFeedback(id=new_id(), submission_id=submission.id, summary=summary, issues_json=json.dumps(issues or [],ensure_ascii=False), detail_markdown=detail_markdown, issue_count=issue_count, needs_revision=normalized != "PASSED", decision=normalized, next_action=next_action, source=source, idempotency_key=idempotency_key)
            changed=db.execute(update(Submission).where(Submission.id==submission.id,Submission.status=="WAITING_REVIEW",Submission.version==submission.version).values(status=target,next_action=next_action,version=submission.version+1).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise DomainError("VERSION_CONFLICT","答案已被另一Agent批改，未重复写入。","回读当前答案及反馈。")
            db.add(review)
            submission.status = target
            submission.next_action = next_action
            submission.version += 1
            if submission.retest_task_id:
                from .models import RetestTask
                task=db.get(RetestTask,submission.retest_task_id)
                if task: task.status=target
            db.flush()
            self._event(db, source, "submission", submission.id, "REVIEW", f"{normalized}: {summary}")
            return review

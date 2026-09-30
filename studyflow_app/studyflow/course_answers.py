"""Whole-course answer sheets; every batch is one transaction, never a loop of API calls."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4
from sqlalchemy import select, func, update
from sqlalchemy.orm import joinedload, selectinload
from .domain import DomainError
from .models import Course, CourseWriteReceipt, Exercise, Lesson, Submission
from .presentation import submission_detail, submission_summary


def _action(formal):
    if formal is None:
        return "FIRST"
    return {"NEEDS_REVISION": "REVISION", "RETEST_REQUIRED": "RETEST"}.get(formal.status, "LOCKED")


def read_answer_sheet(service, course_id: str) -> dict:
    with service.session() as db:
        if not db.get(Course, course_id):
            raise DomainError("OBJECT_NOT_FOUND", "课程不存在。", "先读取 course.detail 确认课程 ID。")
        exercises = db.scalars(select(Exercise).join(Lesson).where(Lesson.course_id == course_id)
                              .order_by(Lesson.position, Exercise.position, Exercise.id)).all()
        ids = [ex.id for ex in exercises]
        rows = db.scalars(select(Submission).where(Submission.exercise_id.in_(ids)).options(
            joinedload(Submission.exercise).joinedload(Exercise.lesson).joinedload(Lesson.course),
            selectinload(Submission.reviews), selectinload(Submission.parent_submission),
            selectinload(Submission.child_submissions),
        ).order_by(Submission.attempt_number, Submission.created_at, Submission.id)).all()
        latest, drafts = {}, {}
        for row in rows:
            (drafts if row.status == "DRAFT" else latest)[row.exercise_id] = row
        answers = []
        for ex in exercises:
            formal, draft = latest.get(ex.id), drafts.get(ex.id)
            action = _action(formal)
            if action == "LOCKED" or (formal and draft and draft.parent_submission_id != formal.id):
                draft = None
            answers.append({"exercise_id": ex.id, "action": action,
                            "draft": submission_detail(draft) if draft else None,
                            "submission": submission_detail(formal) if formal else None})
        return {"course_id": course_id, "answers": answers,
                "next_action": "在本课统一保存或提交；批改仍按题保留原答案和版本链。"}


def write_answers(service, course_id: str, answers, operation: str, idempotency_key: str,
                  source: str = "USER_WEB") -> dict:
    if operation not in {"DRAFT_SAVE", "SUBMIT"}:
        raise DomainError("INVALID_ARGUMENT", "不支持的课程作答操作。", "使用 DRAFT_SAVE 或 SUBMIT。")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise DomainError("INVALID_ARGUMENT", "整课写入需要 1—160 字符的稳定幂等键。", "重试同一载荷时使用原幂等键。")
    if not isinstance(answers, list) or not answers or len(answers) > 500:
        raise DomainError("INVALID_ARGUMENT", "answers 必须是包含 1—500 道题的数组。", "提供本课题目的 exercise_id 和 answer_text。")
    if not isinstance(source, str) or not source or len(source) > 32:
        raise DomainError("INVALID_ARGUMENT", "source 必须是 1—32 字符的文本。", "使用 USER_WEB 或 AGENT_CLI。")
    normalized, seen = [], set()
    allowed = {"exercise_id", "answer_text", "submission_id", "expected_version", "parent_submission_id", "task_id"}
    for entry in answers:
        if not isinstance(entry, dict) or set(entry) - allowed:
            raise DomainError("INVALID_ARGUMENT", "课程答案对象包含未知字段或格式不正确。", "按课程作答契约构造 answers。")
        identifier = entry.get("exercise_id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise DomainError("INVALID_ARGUMENT", "练习 ID 缺失或在同一课程中重复。", "每道题只填写一个答案。")
        if not isinstance(entry.get("answer_text"), str):
            raise DomainError("INVALID_ARGUMENT", "answer_text 必须是文本。", "草稿可为空，正式提交必须完成作答。")
        for name in ("submission_id", "parent_submission_id", "task_id"):
            if entry.get(name) is not None and (not isinstance(entry[name], str) or not entry[name]):
                raise DomainError("INVALID_ARGUMENT", f"{name} 必须是非空 ID。", "重新读取课程作答状态。")
        version = entry.get("expected_version")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 1):
            raise DomainError("INVALID_ARGUMENT", "expected_version 必须是正整数。", "使用读取到的草稿版本。")
        if entry.get("submission_id") and version is None:
            raise DomainError("INVALID_ARGUMENT", "更新已有草稿必须提供 expected_version。", "重新读取课程草稿版本。")
        if operation == "SUBMIT" and not entry["answer_text"].strip():
            raise DomainError("INCOMPLETE_COURSE_ANSWERS", "本课还有空白答案，未提交任何题目。", "完成所有待作答题目后统一提交。")
        normalized.append({name: entry.get(name) for name in sorted(allowed)})
        seen.add(identifier)
    payload = {"course_id": course_id, "operation": operation, "source": source,
               "answers": sorted(normalized, key=lambda item: item["exercise_id"])}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()
    with service.session() as db:
        receipt = db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key == idempotency_key))
        if receipt:
            if receipt.payload_hash != digest:
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于不同的课程答案载荷。", "仅对完全相同的请求使用原幂等键。")
            return json.loads(receipt.result_json)
        if not db.get(Course, course_id):
            raise DomainError("OBJECT_NOT_FOUND", "课程不存在。", "先读取 course.detail 确认课程 ID。")
        ids = list(db.scalars(select(Exercise.id).join(Lesson).where(Lesson.course_id == course_id)).all())
        if not seen.issubset(set(ids)):
            raise DomainError("INVALID_ARGUMENT", "答案包含不属于本课的练习。", "仅提交当前课程的题目。")
        latest = service._latest_attempts(db, ids)
        if operation == "SUBMIT":
            required = {identifier for identifier in ids if _action(latest.get(identifier)) != "LOCKED"}
            if not required.issubset(seen):
                raise DomainError("INCOMPLETE_COURSE_ANSWERS", "本课仍有未提交的题目，未写入任何答案。", "补齐本课所有待作答或待修正题目。")
        written = []
        for entry in normalized:
            identifier = entry["exercise_id"]
            formal = latest.get(identifier)
            action = _action(formal)
            if action == "LOCKED":
                raise DomainError("INVALID_STATE_TRANSITION", "本题已提交，不能覆盖原答案。", "等待批改或按反馈进入修正、复测。")
            parent_id = entry.get("parent_submission_id")
            if formal and parent_id != formal.id:
                raise DomainError("VERSION_CONFLICT", "修正或复测的父作答已经变化。", "重新读取课程反馈后再作答。")
            if not formal and parent_id:
                raise DomainError("INVALID_ARGUMENT", "首次作答不能指定其他父记录。", "重新读取本课作答状态。")
            service._check_task(db, entry.get("task_id"))
            row = db.get(Submission, entry["submission_id"]) if entry.get("submission_id") else None
            if entry.get("submission_id"):
                if not row or row.status != "DRAFT" or row.exercise_id != identifier or row.parent_submission_id != parent_id:
                    raise DomainError("INVALID_STATE_TRANSITION", "草稿不属于本题当前可编辑版本。", "重新读取课程草稿。")
                if row.version != entry["expected_version"]:
                    raise DomainError("VERSION_CONFLICT", "草稿版本已发生变化，整课操作已回滚。", "重新读取草稿并保留本设备临时内容。")
                next_version = row.version + 1
                status = "WAITING_REVIEW" if operation == "SUBMIT" else "DRAFT"
                next_action = "等待外部 Agent 批改" if operation == "SUBMIT" else "继续编辑课程草稿。"
                changed = db.execute(update(Submission).where(Submission.id == row.id, Submission.version == row.version,
                    Submission.status == "DRAFT").values(answer_text=entry["answer_text"], version=next_version,
                    status=status, next_action=next_action, source=source).execution_options(synchronize_session=False))
                if changed.rowcount != 1:
                    raise DomainError("VERSION_CONFLICT", "草稿版本冲突，整课操作已回滚。", "重新读取课程状态。")
                db.expire(row); db.refresh(row)
            else:
                existing = db.scalar(select(Submission).where(Submission.exercise_id == identifier, Submission.status == "DRAFT",
                    Submission.parent_submission_id == parent_id))
                if existing:
                    raise DomainError("VERSION_CONFLICT", "本题已有草稿，版本未确认。", "先读取已有草稿及版本，避免覆盖其他窗口的答案。")
                attempt = (db.scalar(select(func.max(Submission.attempt_number)).where(Submission.exercise_id == identifier)) or 0) + 1
                row = Submission(id=str(uuid4()), exercise_id=identifier, parent_submission_id=parent_id,
                    task_id=entry.get("task_id") or (formal.task_id if formal else None), answer_text=entry["answer_text"],
                    source=source, status="WAITING_REVIEW" if operation == "SUBMIT" else "DRAFT", version=1,
                    attempt_number=attempt, attempt_kind=action,
                    next_action="等待外部 Agent 批改" if operation == "SUBMIT" else "继续编辑课程草稿。")
                db.add(row); db.flush()
            task = service._check_task(db, row.task_id)
            if operation == "SUBMIT" and task and task.status == "TODO":
                task.status = "IN_PROGRESS"
            service._event(db, source, "submission", row.id, operation, "整课统一保存" if operation == "DRAFT_SAVE" else "整课统一提交")
            written.append(submission_summary(row))
        result = {"course_id": course_id, "status": "DRAFT" if operation == "DRAFT_SAVE" else "WAITING_REVIEW",
                  "submissions": written, "next_action": "继续课程作答。" if operation == "DRAFT_SAVE" else "本课已提交；等待外部 Agent 批改。"}
        db.add(CourseWriteReceipt(id=str(uuid4()), idempotency_key=idempotency_key, course_id=course_id,
            operation=operation, payload_hash=digest, result_json=json.dumps(result, ensure_ascii=False)))
        db.flush()
        return result

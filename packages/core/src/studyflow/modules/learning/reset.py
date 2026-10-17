"""Explicit course-scoped maintenance, separate from evidence-free learner restart."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlalchemy import delete, select, update, exists, or_
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.courses.models import Course, Exercise, Lesson
from .models import CourseStudySession, CourseWriteReceipt, LearningProgress, Submission
from .write_contract import digest


def current_submission_predicate():
    """Sealed rounds remain history, not actionable work; legacy answers survive first open."""
    sealed = exists(select(CourseStudySession.id).where(
        CourseStudySession.id == Submission.study_session_id,
        CourseStudySession.abandoned_at.is_not(None)))
    legacy_reset = exists(select(CourseStudySession.id).join(
        Lesson, Lesson.course_id == CourseStudySession.course_id).where(
        Lesson.id == Exercise.lesson_id, CourseStudySession.revision >= 2))
    # The legacy condition is correlated through Exercise, so callers must join the exercise.
    return ~sealed & or_(Submission.study_session_id.is_not(None), ~legacy_reset)


def preserve_legacy_round(db, service, course_id, key):
    """Before replacing pre-round material, retain a boundary snapshot for legacy evidence.

    This is a maintenance snapshot, not a learner-created attempt or a mastery claim.
    It makes the next normal open revision 2 so unbound old answers cannot leak forward.
    """
    if db.scalar(select(CourseStudySession.id).where(CourseStudySession.course_id == course_id).limit(1)):
        return
    legacy = db.scalar(select(Submission.id).join(Exercise).join(Lesson).where(
        Lesson.course_id == course_id, Submission.study_session_id.is_(None)).limit(1))
    progress = db.scalar(select(LearningProgress.id).where(LearningProgress.course_id == course_id).limit(1))
    if not legacy and not progress:
        return
    from studyflow.infrastructure.runtime import Runtime
    from .service import LearningService
    from .study_sessions import capture
    reader = LearningService(Runtime(service.settings, service.session_factory, read_only=True))
    text, content_hash = capture(reader, course_id)
    identifier = new_id()
    db.add(CourseStudySession(id=identifier, course_id=course_id, revision=1,
        idempotency_key="legacy-boundary-" + digest({"course": course_id, "key": key}),
        new_version=False, snapshot_json=text, content_hash=content_hash,
        progress_json="{}", version=1))
    db.flush()
    service._event(db, "AGENT_CLI", "course_study", identifier, "LEGACY_BOUNDARY",
                   "课程覆盖前保留旧材料边界；不是新增学习或作答证据")


def seal_current(db, service, course_id, reason):
    """Caller owns the transaction/lease; neither content nor notes are deleted."""
    ids = list(db.scalars(select(CourseStudySession.id).where(
        CourseStudySession.course_id == course_id, CourseStudySession.abandoned_at.is_(None))))
    if ids:
        db.execute(update(CourseStudySession).where(CourseStudySession.id.in_(ids)).values(
            abandoned_at=datetime.now(timezone.utc).replace(tzinfo=None),
            version=CourseStudySession.version + 1).execution_options(synchronize_session=False))
        for identifier in ids:
            service._event(db, "AGENT_CLI", "course_study", identifier, "ABANDON", reason)
    cleared = db.execute(delete(LearningProgress).where(LearningProgress.course_id == course_id)).rowcount
    return ids, cleared


def _inventory(db, service, course_id):
    if not isinstance(course_id, str) or not course_id.strip():
        raise DomainError("INVALID_ARGUMENT", "课程ID必须是非空文本。")
    course = db.get(Course, course_id)
    if course is None:
        raise DomainError("OBJECT_NOT_FOUND", "课程不存在；未重置任何记录。")
    from .study_sessions import capture
    from .english.models import EnglishStudyState
    from studyflow.infrastructure.runtime import Runtime
    from .service import LearningService
    reader = LearningService(Runtime(service.settings, service.session_factory, read_only=True))
    rounds = list(db.scalars(select(CourseStudySession).where(
        CourseStudySession.course_id == course_id).order_by(CourseStudySession.id)))
    active = [row for row in rounds if row.abandoned_at is None]
    if active:
        from .restart import latest_content
        text, content_hash = latest_content(reader, max(active, key=lambda row: row.revision))
    else:
        text, content_hash = capture(reader, course_id)
    exercises = select(Exercise.id).join(Lesson).where(Lesson.course_id == course_id)
    answers = list(db.execute(select(Submission.id, Submission.version, Submission.status).where(
        Submission.exercise_id.in_(exercises)).order_by(Submission.id)))
    training = list(db.execute(select(EnglishStudyState.study_session_id, EnglishStudyState.version).where(
        EnglishStudyState.study_session_id.in_([row.id for row in rounds])).order_by(EnglishStudyState.study_session_id)))
    receipts = list(db.scalars(select(CourseWriteReceipt.id).where(
        CourseWriteReceipt.course_id == course_id).order_by(CourseWriteReceipt.id)))
    progress = list(db.execute(select(LearningProgress.id, LearningProgress.progress_percent,
        LearningProgress.status, LearningProgress.last_position).where(
        LearningProgress.course_id == course_id).order_by(LearningProgress.id)))
    state = {"course_id": course_id, "content_revision": course.version,
        "content_hash": content_hash,
        "rounds": [(row.id, row.version, row.abandoned_at.isoformat() if row.abandoned_at else None) for row in rounds],
        "answers": [tuple(row) for row in answers], "training": [tuple(row) for row in training],
        "receipts": receipts, "progress": [tuple(row) for row in progress]}
    return text, rounds, {"ok": True, "course_id": course_id, "content_revision": course.version,
        "state_hash": digest(state), "content_hash": content_hash,
        "active_study_sessions": [row.id for row in rounds if row.abandoned_at is None],
        "counts": {"active_rounds": sum(row.abandoned_at is None for row in rounds),
                   "answer_records_retained": len(answers), "legacy_reading_progress_cleared": len(progress)},
        "notes_retained": True, "history_retained": True,
        "effect": "重置本课当前阅读、作答和训练状态并采用最新材料；旧作答封存，不再进入当前待处理队列。"}


def preview(service, course_id):
    with service.session(read_only=True) as db:
        return _inventory(db, service, course_id)[2]


def apply(service, course_id, expected_state_hash, expected_content_hash, idempotency_key, confirm=False):
    if confirm is not True:
        raise DomainError("CONFIRMATION_REQUIRED", "重置学习状态必须显式确认；未改动数据。")
    for value in (expected_state_hash, expected_content_hash):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise DomainError("INVALID_ARGUMENT", "需要预览返回的state_hash和content_hash。")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise DomainError("INVALID_ARGUMENT", "需要1—160字符的稳定幂等键。")
    payload = {"course_id": course_id, "state_hash": expected_state_hash, "content_hash": expected_content_hash}
    request_hash = digest(payload)
    with service.session() as db:
        old_receipt = db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key == idempotency_key))
        if old_receipt:
            if old_receipt.operation != "LEARNING_RESET" or old_receipt.payload_hash != request_hash:
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "该幂等键已用于其他请求，未重置。")
            return json.loads(old_receipt.result_json)
        from studyflow.modules.courses.models import CourseRevision
        if db.scalar(select(CourseRevision.id).where(CourseRevision.idempotency_key == idempotency_key)):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "该幂等键已用于课程发布。")
        if db.scalar(select(CourseStudySession.id).where(CourseStudySession.idempotency_key == idempotency_key)):
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "该幂等键已用于开始学习。")
        text, rounds, info = _inventory(db, service, course_id)
        if info["content_hash"] != expected_content_hash:
            raise DomainError("COURSE_CONTENT_CONFLICT", "预览后课程材料已变化；请重新预览，未重置。")
        if info["state_hash"] != expected_state_hash:
            raise DomainError("VERSION_CONFLICT", "预览后学习记录已变化；请重新预览确认，未重置。")
        ids, cleared = seal_current(db, service, course_id, "用户授权外部Agent重置本课并采用最新材料")
        identifier = new_id()
        # Revision >=2 deliberately excludes pre-round legacy submissions from the new answer sheet.
        revision = max(2, max((row.revision for row in rounds), default=0) + 1)
        db.add(CourseStudySession(id=identifier, course_id=course_id, revision=revision,
            idempotency_key=idempotency_key, new_version=True, snapshot_json=text,
            content_hash=info["content_hash"], progress_json="{}", version=1))
        db.flush()
        result = {"ok": True, "course_id": course_id, "learning_state_reset": True,
            "study_session_id": identifier, "reset_study_sessions": ids,
            "content_revision": info["content_revision"], "content_hash": info["content_hash"],
            "cleared_legacy_progress": cleared, "history_retained": True, "notes_retained": True}
        db.add(CourseWriteReceipt(id=new_id(), idempotency_key=idempotency_key, course_id=course_id,
            study_session_id=identifier, operation="LEARNING_RESET", payload_hash=request_hash,
            result_json=json.dumps(result, ensure_ascii=False)))
        service._event(db, "AGENT_CLI", "course", course_id, "RESET_LEARNING", "获授权重置当前状态并采用最新材料，历史与笔记保留")
        db.flush()
        return result

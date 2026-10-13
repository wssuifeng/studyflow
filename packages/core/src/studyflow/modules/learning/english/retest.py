"""No-hint retest drafts and immutable final attempts; caller owns the transaction."""
import json
from sqlalchemy import select, update
from studyflow.modules.learning.models import Submission, SubmissionChainLink
from studyflow.modules.learning.english.models import EnglishCheckAttempt
from studyflow.modules.learning.english.checker import check_answer, tokenize
from studyflow.modules.reviews.models import RetestTask
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate, EnglishErrorEvidence, EnglishReviewItem
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id


def require(db, task_id, active=False):
    task = db.get(RetestTask, task_id)
    if not task or task.task_mode != "english":
        raise DomainError("OBJECT_NOT_FOUND", "英语复测任务不存在。")
    if active and task.status not in {"READY", "IN_PROGRESS"}:
        raise DomainError("INVALID_STATE_TRANSITION", "复测已结束，请回读结果或创建新任务。")
    return task


def answer(db, task_id):
    return db.scalar(select(Submission).where(Submission.retest_task_id == task_id).order_by(Submission.created_at.desc(), Submission.id.desc()))


def get(db, task_id):
    task = require(db, task_id)
    payload = json.loads(task.payload_json)
    row = answer(db, task_id)
    attempt = db.scalar(select(EnglishCheckAttempt).where(EnglishCheckAttempt.retest_task_id == task_id))
    return {"task_id": task.id, "study_session_id": task.study_session_id, "exercise_id": payload["exercise_id"],
            "title": task.title, "prompt": task.prompt, "token_count": len(tokenize(payload["spec"]["target"])),
            "status": task.status, "answer_text": row.answer_text if row else "", "answer_version": row.version if row else 0,
            "result": json.loads(attempt.result_json) if attempt else None}


def save(db, task_id, answer_text, expected_version):
    task = require(db, task_id, active=True)
    if not isinstance(answer_text, str) or len(answer_text) > 4000 or isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
        raise DomainError("INVALID_ARGUMENT", "复测草稿需要最多4000字符的文本和非负版本。")
    row = answer(db, task_id)
    if expected_version != (row.version if row else 0):
        raise DomainError("VERSION_CONFLICT", "复测草稿已变化；未覆盖其他窗口。")
    if row and row.status != "DRAFT": raise DomainError("ANSWER_LOCKED", "复测原答案不可覆盖。")
    if row:
        changed = db.execute(update(Submission).where(Submission.id == row.id, Submission.version == expected_version)
                             .values(answer_text=answer_text, version=expected_version+1).execution_options(synchronize_session=False))
        if changed.rowcount != 1: raise DomainError("VERSION_CONFLICT", "复测草稿版本冲突。")
        db.expire(row)
    else:
        payload = json.loads(task.payload_json)
        # A provisional draft is not a correction-chain claim until final confirmation.
        row = Submission(id=new_id(), exercise_id=payload["exercise_id"], study_session_id=task.study_session_id,
                         retest_task_id=task.id, answer_text=answer_text, status="DRAFT", version=1,
                         attempt_kind="RETEST", source="USER_ENGINE")
        db.add(row); db.flush()
    task.status = "IN_PROGRESS"
    return {"task_id": task.id, "answer_version": row.version, "status": task.status}


def check(db, task_id, answer_text, expected_version=None):
    task = require(db, task_id, active=True)
    if not isinstance(answer_text, str) or not answer_text.strip() or len(answer_text) > 4000:
        raise DomainError("ANSWER_EMPTY", "复测需要非空且最多4000字符的答案。")
    row = answer(db, task_id)
    if expected_version is not None and (isinstance(expected_version, bool) or expected_version != (row.version if row else 0)):
        raise DomainError("VERSION_CONFLICT", "复测草稿已变化，未提交旧版本。")
    if row and row.status != "DRAFT": raise DomainError("ANSWER_LOCKED", "复测已确认。")
    payload = json.loads(task.payload_json)
    aggregate = db.get(EnglishErrorAggregate, payload["aggregate_id"])
    result = check_answer(payload["spec"], answer_text)
    parent = db.get(Submission, task.parent_submission_id)
    while db.get(SubmissionChainLink, parent.id):
        parent = db.get(Submission, db.get(SubmissionChainLink, parent.id).child_id)
    if row is None:
        row = Submission(id=new_id(), exercise_id=payload["exercise_id"], study_session_id=task.study_session_id,
                         retest_task_id=task.id, answer_text=answer_text, version=0, source="USER_ENGINE")
    from studyflow.modules.learning.write_contract import claim_parent
    claim_parent(db, parent, row.id, "USER_ENGINE")
    row.parent_submission_id = parent.id; row.attempt_number = parent.attempt_number+1
    row.attempt_kind = "RETEST"; row.answer_text = answer_text; row.version += 1
    row.status = "RECHECKED" if result["matched"] else "RETEST_REQUIRED"
    db.add(row); db.flush()
    attempt = EnglishCheckAttempt(id=new_id(), study_session_id=task.study_session_id, exercise_id=payload["exercise_id"],
                                 submission_id=row.id, answer_version=row.version, answer_text=answer_text,
                                 rule_hash=payload["rule_hash"], result_json=json.dumps(result), assisted=False, retest_task_id=task.id)
    db.add(attempt); db.flush()
    aggregate.latest_attempt_id = attempt.id; aggregate.version += 1
    review = db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id == aggregate.id))
    if result["matched"]:
        review.status = "PASSED_THIS_TIME"; task.status = "PASSED"
    else:
        db.add(EnglishErrorEvidence(id=new_id(), aggregate_id=aggregate.id, attempt_id=attempt.id, round_key=task.id, valid_error=True))
        aggregate.failed_attempts += 1; aggregate.failed_rounds += 1; aggregate.archived = False
        review.status = "PENDING"; task.status = "RETEST_REQUIRED"
    return {**result, "task_id": task.id, "submission_id": row.id, "status": task.status,
            "aggregate_version": aggregate.version, "answer_version": row.version}

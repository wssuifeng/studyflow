from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload
from studyflow.modules.courses.models import Course, Exercise, Lesson
from studyflow.modules.learning.models import Submission
from studyflow.shared.constants import QUEUE_STATUSES




def queue_submissions(db: Session, plan_line_id: str | None = None) -> list[Submission]:
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
    from studyflow.modules.learning.write_contract import effective_rows
    all_rows = db.scalars(select(Submission)).all()
    active = {row.id for row in effective_rows(db, all_rows)}
    return [row for row in rows if row.id in active and not any(child.id in active and child.status != "DRAFT" for child in row.child_submissions)]


def decorate_queue(submissions: list[Submission]) -> list[Submission]:
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

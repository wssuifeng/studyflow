import json
from sqlalchemy import select
from studyflow.modules.mistakes.english.models import EnglishReviewItem,EnglishErrorEvidence
from studyflow.modules.learning.english.models import EnglishCheckAttempt
from studyflow.modules.learning.models import Submission
from studyflow.modules.reviews.models import RetestTask
from studyflow.modules.learning.study_sessions import frozen_context
from studyflow.modules.learning.write_contract import digest
from studyflow.shared.ids import new_id
from studyflow.shared.domain import DomainError


def publish(db,aggregate,expected_version,key):
    if db.scalar(select(RetestTask.id).where(RetestTask.idempotency_key==key)):
        raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已有其他复测任务，未创建或替换任务。")
    if aggregate.version!=expected_version:raise DomainError("VERSION_CONFLICT","错误摘要已经变化。")
    review=db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id==aggregate.id))
    if not review or review.status not in {"PENDING","RETESTING","PASSED_THIS_TIME","AGENT_ACCEPTED"}:raise DomainError("REVIEW_NOT_SELECTED","先将本项收录到复习清单。")
    if review.retest_task_id:
        current=db.get(RetestTask,review.retest_task_id)
        if current and current.status in {"READY","IN_PROGRESS"}:return {"task_id":current.id,"title":current.title,"prompt":current.prompt,"status":current.status}
    evidence=db.scalar(select(EnglishErrorEvidence).where(EnglishErrorEvidence.aggregate_id==aggregate.id,EnglishErrorEvidence.valid_error==True).order_by(EnglishErrorEvidence.created_at.desc(),EnglishErrorEvidence.id.desc()))
    attempt=db.get(EnglishCheckAttempt,evidence.attempt_id) if evidence and evidence.attempt_id else None
    parent=db.get(Submission,attempt.submission_id) if attempt else None
    if not parent:raise DomainError("AGENT_RETEST_REQUIRED","本项仅有Agent证据，请由Agent发布迁移/复测题。")
    # RetestTask's legacy 1:1 parent constraint stays intact; repeat tests chain through the prior answer.
    if review.retest_task_id:
        previous=db.scalar(select(Submission).where(Submission.retest_task_id==review.retest_task_id).order_by(Submission.created_at.desc()))
        if previous:parent=previous
    if db.scalar(select(RetestTask.id).where(RetestTask.parent_submission_id==parent.id)):raise DomainError("RETEST_TASK_EXISTS","同一父答案已有复测任务，保留既有任务。")
    frozen=frozen_context(parent);exercise=frozen["exercise"]
    payload={"aggregate_id":aggregate.id,"exercise_id":parent.exercise_id,"spec":exercise["english"],"prompt":exercise["prompt"],"rule_hash":aggregate.rule_hash}
    task=RetestTask(id=new_id(),parent_submission_id=parent.id,study_session_id=parent.study_session_id,title="无提示回忆 · "+exercise["title"],prompt=exercise["prompt"],requirements="不查看参考或听目标语音，重新输入。",objective="原冻结训练项的无提示回忆",agent_reference="",status="READY",idempotency_key=key,payload_hash=digest(payload),task_mode="english",payload_json=json.dumps(payload,ensure_ascii=False))
    db.add(task);db.flush();review.retest_task_id=task.id;review.status="RETESTING";aggregate.version+=1
    return {"task_id":task.id,"title":task.title,"prompt":task.prompt,"status":task.status}

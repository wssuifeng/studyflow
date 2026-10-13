"""Rebuildable error projections; the source answer is never copied."""
import json
from sqlalchemy import select,func
from studyflow.modules.mistakes.query.scope import notebook
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate,EnglishErrorEvidence,EnglishReviewItem
from studyflow.modules.learning.english.models import EnglishStudyState
from studyflow.shared.ids import new_id


def select_review(db,aggregate,reason):
    item=db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id==aggregate.id))
    if item is None:item=EnglishReviewItem(id=new_id(),aggregate_id=aggregate.id,reason=reason,status="PENDING");db.add(item)
    else:item.status="PENDING";item.reason=reason
    aggregate.archived=False;aggregate.version+=1
    return item


def record_check(db,study,frozen,item,attempt):
    result=json.loads(attempt.result_json)
    plan=db.get(EnglishStudyState,study.id)
    book=notebook(db,plan.plan_line_id if plan else frozen["course"].get("plan_line_id"),"english",create=result.get("matched") is False)
    if book is None:return
    aggregate=db.scalar(select(EnglishErrorAggregate).where(EnglishErrorAggregate.notebook_id==book.id,EnglishErrorAggregate.course_id==study.course_id,EnglishErrorAggregate.exercise_key==item["id"],EnglishErrorAggregate.rule_hash==attempt.rule_hash))
    if aggregate is None and result.get("matched") is False:
        aggregate=EnglishErrorAggregate(id=new_id(),notebook_id=book.id,course_id=study.course_id,exercise_key=item["id"],rule_hash=attempt.rule_hash,objective_ids_json=json.dumps(item["english"].get("objective_ids",[])),failed_attempts=0,failed_rounds=0,version=1,archived=False)
        db.add(aggregate);db.flush()
    if aggregate is None:return
    aggregate.latest_attempt_id=attempt.id;aggregate.version+=1
    if result.get("matched") is False:
        round_key=attempt.retest_task_id or study.id
        prior=db.scalar(select(EnglishErrorEvidence.id).where(EnglishErrorEvidence.aggregate_id==aggregate.id,EnglishErrorEvidence.round_key==round_key).limit(1))
        db.add(EnglishErrorEvidence(id=new_id(),aggregate_id=aggregate.id,attempt_id=attempt.id,round_key=round_key,valid_error=True))
        aggregate.failed_attempts+=1;aggregate.failed_rounds+=int(not prior);aggregate.archived=False
        review=db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id==aggregate.id))
        if review or attempt.retest_task_id:select_review(db,aggregate,"RETEST_FAILED" if attempt.retest_task_id else "NEW_FAILURE")
    elif result.get("matched") and attempt.retest_task_id and not attempt.assisted:
        review=db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id==aggregate.id))
        if review:review.status="PASSED_THIS_TIME"
    db.flush()

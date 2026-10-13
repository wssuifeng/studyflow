"""Fold accepted review facts into their appropriate domain, in the review transaction."""
import json,hashlib
from sqlalchemy import select
from studyflow.modules.learning.study_sessions import frozen_context
from studyflow.modules.learning.english.models import EnglishSubmissionDetail,EnglishCheckAttempt
from studyflow.modules.learning.english.checker import rule_hash
from studyflow.modules.mistakes.query.scope import notebook
from studyflow.modules.mistakes.general.models import GeneralMistakeEntry,GeneralMistakeOccurrence
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate,EnglishErrorEvidence
from studyflow.shared.ids import new_id


def record_review(db,submission,review):
    frozen=frozen_context(submission)
    if not frozen:return # Unversioned historical evidence must not be assigned using today's plan.
    course=frozen["course"];exercise=frozen["exercise"]
    failed=review.decision!="PASSED"
    domain="english" if "english" in exercise else "general"
    book=notebook(db,course.get("plan_line_id"),domain,create=failed)
    if not book:return
    if domain=="english":
        spec=exercise["english"];rh=rule_hash(spec,exercise["prompt"])
        aggregate=db.scalar(select(EnglishErrorAggregate).where(EnglishErrorAggregate.notebook_id==book.id,EnglishErrorAggregate.course_id==course["id"],EnglishErrorAggregate.exercise_key==exercise["id"],EnglishErrorAggregate.rule_hash==rh))
        if not failed:
            # A declared alternative was accepted by the Agent: historical raw mismatches remain.
            attempts=db.scalars(select(EnglishCheckAttempt).where(EnglishCheckAttempt.submission_id==submission.id,EnglishCheckAttempt.answer_text==submission.answer_text,EnglishCheckAttempt.rule_hash==rh)).all()
            for attempt in attempts:
                evidence=db.scalar(select(EnglishErrorEvidence).where(EnglishErrorEvidence.attempt_id==attempt.id))
                if evidence:evidence.valid_error=False
            if aggregate:
                from studyflow.modules.mistakes.english.models import EnglishReviewItem
                entry=db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id==aggregate.id))
                if entry:entry.status="AGENT_ACCEPTED"
                aggregate.version+=1
            return
        if aggregate is None:
            aggregate=EnglishErrorAggregate(id=new_id(),notebook_id=book.id,course_id=course["id"],exercise_key=exercise["id"],rule_hash=rh,objective_ids_json=json.dumps(spec.get("objective_ids",[])),failed_attempts=0,failed_rounds=0,version=1,archived=False);db.add(aggregate);db.flush()
        # If this same answer already has an exact-check failure, attach the feedback without counting twice.
        detail=db.get(EnglishSubmissionDetail,submission.id)
        attempt=db.get(EnglishCheckAttempt,detail.last_attempt_id) if detail and detail.last_attempt_id else None
        if not attempt or json.loads(attempt.result_json).get("matched") is not False:
            prior=db.scalar(select(EnglishErrorEvidence.id).where(EnglishErrorEvidence.aggregate_id==aggregate.id,EnglishErrorEvidence.round_key==submission.study_session_id).limit(1))
            db.add(EnglishErrorEvidence(id=new_id(),aggregate_id=aggregate.id,feedback_id=review.id,round_key=submission.study_session_id,valid_error=True));aggregate.failed_attempts+=1;aggregate.failed_rounds+=int(not prior)
        from studyflow.modules.mistakes.english.projection import select_review
        select_review(db,aggregate,"AGENT_REVISION")
        return
    rh=hashlib.sha256(json.dumps({k:exercise.get(k) for k in ["prompt","requirements","type"]},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    entry=db.scalar(select(GeneralMistakeEntry).where(GeneralMistakeEntry.notebook_id==book.id,GeneralMistakeEntry.course_id==course["id"],GeneralMistakeEntry.exercise_key==exercise["id"],GeneralMistakeEntry.rule_hash==rh))
    if not entry and not failed:return
    if entry is None:
        entry=GeneralMistakeEntry(id=new_id(),notebook_id=book.id,course_id=course["id"],exercise_key=exercise["id"],rule_hash=rh,latest_feedback_id=review.id,status=review.decision,version=1,archived=False);db.add(entry);db.flush()
    else:entry.latest_feedback_id=review.id;entry.status=review.decision;entry.version+=1
    if failed:
        entry.archived=False
        db.add(GeneralMistakeOccurrence(id=new_id(),entry_id=entry.id,feedback_id=review.id))

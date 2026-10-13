"""Bounded provenance view; supplemental completion never clears original mistakes."""
import json
from sqlalchemy import select, func
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.models import Course
from studyflow.modules.learning.models import CourseStudySession, Submission
from studyflow.modules.learning.english.models import EnglishStudyState, EnglishSubmissionDetail
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate, EnglishErrorEvidence
from .models import EnglishRemediationCourse, EnglishRemediationSource


def course_view(db, profile, include_sources=False):
    course=db.get(Course,profile.course_id)
    study=db.scalar(select(CourseStudySession).where(CourseStudySession.course_id==course.id).order_by(CourseStudySession.revision.desc()).limit(1))
    state=db.get(EnglishStudyState,study.id) if study else None
    status="COMPLETED" if state and state.completed else "IN_PROGRESS" if study else "NOT_STARTED"
    result={"course_id":course.id,"title":course.title,"summary":course.summary,"plan_line_id":profile.plan_line_id,"track":"SUPPLEMENT","objective_ids":json.loads(profile.objective_ids_json),"rationale":profile.rationale,"learning_status":status,"study_session_id":study.id if study else None,"auto_resolves_original_errors":False}
    result.update(transfer_status="NOT_ATTEMPTED",transfer_total=0,transfer_unassisted_passed=0)
    if study:
        from studyflow.modules.learning.english.service import get_view
        transfers=[i for i in get_view(db,study.id)["items"] if i.get("progression",{} ) and i["progression"]["stage"]=="transfer"]
        passed=lambda i:i["matched"] is True or i["status"] in {"PASSED","RECHECKED","REVIEWED"}
        # A corrected child answer must not erase an earlier reveal in this round.
        # A later explicitly opened round is independent because study_session_id differs.
        assisted_items=set(db.scalars(select(Submission.exercise_id).join(EnglishSubmissionDetail,EnglishSubmissionDetail.submission_id==Submission.id).where(
            Submission.study_session_id==study.id,Submission.retest_task_id.is_(None),EnglishSubmissionDetail.assisted==True,
        )).all())
        independent=sum(passed(i) and not i["assisted"] and i["exercise_id"] not in assisted_items for i in transfers)
        result.update(transfer_total=len(transfers),transfer_unassisted_passed=independent)
        result["transfer_status"]="UNASSISTED_PASS" if transfers and independent==len(transfers) else "ASSISTED_PASS" if transfers and all(passed(i) for i in transfers) else "PENDING"
    if include_sources:
        rows=db.scalars(select(EnglishRemediationSource).where(EnglishRemediationSource.course_id==course.id).order_by(EnglishRemediationSource.id)).all()
        result["sources"]=[]
        for row in rows:
            agg=db.get(EnglishErrorAggregate,row.aggregate_id);ev=db.get(EnglishErrorEvidence,row.evidence_id);origin=db.get(Course,agg.course_id)
            result["sources"].append({"aggregate_id":row.aggregate_id,"evidence_id":row.evidence_id,"source_version":row.source_version,"rule_hash":row.rule_hash,"source_course_id":agg.course_id,"source_course_title":origin.title,"current_version":agg.version,"evidence_still_valid":bool(ev.valid_error),"archived":agg.archived})
    return result


def get_course(db, course_id):
    profile=db.get(EnglishRemediationCourse,course_id)
    if not profile:raise DomainError("OBJECT_NOT_FOUND","补充学习课程不存在。")
    return course_view(db,profile,True)


def list_courses(db, plan_line_id, source_course_id=None, aggregate_id=None, limit=30, offset=0):
    from studyflow.modules.planning.models import PlanLine
    if not db.get(PlanLine,plan_line_id):raise DomainError("OBJECT_NOT_FOUND","计划不存在。")
    query=select(EnglishRemediationCourse).where(EnglishRemediationCourse.plan_line_id==plan_line_id)
    if source_course_id or aggregate_id:
        refs=select(EnglishRemediationSource.course_id).join(EnglishErrorAggregate,EnglishErrorAggregate.id==EnglishRemediationSource.aggregate_id)
        if source_course_id:refs=refs.where(EnglishErrorAggregate.course_id==source_course_id)
        if aggregate_id:refs=refs.where(EnglishRemediationSource.aggregate_id==aggregate_id)
        query=query.where(EnglishRemediationCourse.course_id.in_(refs))
    total=db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows=db.scalars(query.order_by(EnglishRemediationCourse.created_at,EnglishRemediationCourse.course_id).offset(offset).limit(limit)).all()
    return {"plan_line_id":plan_line_id,"items":[course_view(db,p) for p in rows],"total":total,"next_offset":offset+len(rows) if offset+len(rows)<total else None}

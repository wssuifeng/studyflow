"""Bounded positive and negative learning evidence; never estimates mastery."""
import json
from sqlalchemy import select,or_,and_
from studyflow.shared.domain import DomainError
from .models import CourseStudySession,CourseReferenceView,Submission
from .study_sessions import outcome,study_attempts
from studyflow.modules.planning.models import PlanCourseItem,PlanLine


def read_evidence(service,plan_line_id,course_id=None,learning_mode=None,limit=20,cursor=None):
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100:raise DomainError("INVALID_ARGUMENT","limit须1—100。")
    if learning_mode not in (None,"general","english"):raise DomainError("INVALID_ARGUMENT","未知学习模式。")
    with service.session(read_only=True) as db:
        if not db.get(PlanLine,plan_line_id):raise DomainError("OBJECT_NOT_FOUND","计划不存在。")
        query=select(CourseStudySession).where(CourseStudySession.course_id.in_(select(PlanCourseItem.course_id).where(PlanCourseItem.plan_line_id==plan_line_id)))
        if course_id:query=query.where(CourseStudySession.course_id==course_id)
        if cursor:
            anchor=db.get(CourseStudySession,cursor)
            if not anchor:raise DomainError("INVALID_ARGUMENT","分页轮次不存在。")
            query=query.where(or_(CourseStudySession.created_at<anchor.created_at,and_(CourseStudySession.created_at==anchor.created_at,CourseStudySession.id<anchor.id)))
        rows=db.scalars(query.order_by(CourseStudySession.created_at.desc(),CourseStudySession.id.desc()).limit(limit+1)).all()
        result=[]
        for row in rows[:limit]:
            frozen=json.loads(row.snapshot_json);course=frozen["course"]
            if course.get("plan_line_id")!=plan_line_id or learning_mode and course.get("learning_mode","general")!=learning_mode:continue
            attempts=study_attempts(db,row);hint_ids=set(db.scalars(select(CourseReferenceView.exercise_id).where(CourseReferenceView.study_session_id==row.id)))
            questions=[e for l in frozen["lessons"] for e in l["exercises"]]
            result.append({"study_session_id":row.id,"course_id":row.course_id,"plan_line_id":plan_line_id,"learning_mode":course.get("learning_mode","general"),"content_revision":course.get("content_revision"),"snapshot_hash":row.content_hash,"created_at":row.created_at.isoformat(),"abandoned":row.abandoned_at is not None,**outcome(db,row),"hint_information":"recorded_since_1.8" if row.hint_tracking_enabled else "legacy_unknown","hinted_exercise_count":len(hint_ids),"mastery":"not_inferred","exercise_count":len(questions),"exercise_sample":[{"exercise_id":ex["id"],"status":attempts[ex["id"]].status if ex["id"] in attempts else "NOT_SUBMITTED","attempt_kind":attempts[ex["id"]].attempt_kind if ex["id"] in attempts else None,"submission_id":attempts[ex["id"]].id if ex["id"] in attempts else None,"hint_used":ex["id"] in hint_ids if row.hint_tracking_enabled else None} for ex in questions[:20]],"exercise_sample_truncated":len(questions)>20})
        return {"items":result,"scanned":min(limit,len(rows)),"next_cursor":rows[limit-1].id if len(rows)>limit else None,"scope":{"plan_line_id":plan_line_id,"course_id":course_id,"learning_mode":learning_mode},"note":"首次、修正、复测和提示是证据，不自动等同独立掌握；更多题面按ID读取。"}

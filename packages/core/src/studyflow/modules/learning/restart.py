"""Explicit, evidence-guarded restart of an unsubmitted general learning round."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select, or_, update
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from .models import CourseStudySession, CourseWriteReceipt, Submission
from .study_sessions import require_study, exercise_ids, capture, detail


def blockers(db, study):
    reasons=[]
    content=json.loads(study.snapshot_json)
    if content["course"].get("learning_mode","general")!="general":
        reasons.append({"code":"ENGLISH_RESTART_UNSUPPORTED","message":"英语轮次含训练状态，暂不使用普通课程重开入口。"})
    if db.scalar(select(Submission.id).where(or_(Submission.study_session_id==study.id,
        (Submission.study_session_id.is_(None)) & Submission.exercise_id.in_(exercise_ids(study)))) .limit(1)):
        reasons.append({"code":"ANSWER_HISTORY_PRESENT","message":"已有题目草稿或作答记录，不能放弃本轮。"})
    if db.scalar(select(CourseWriteReceipt.id).where(CourseWriteReceipt.study_session_id==study.id,
        CourseWriteReceipt.operation.notin_(["STUDY_OPEN","STUDY_RESTART"])).limit(1)):
        reasons.append({"code":"ANSWER_WRITE_PRESENT","message":"已有作答写入回执，请继续本轮并确认写入结果。"})
    from .english.models import EnglishCheckAttempt, EnglishStudyState
    if db.scalar(select(EnglishCheckAttempt.id).where(EnglishCheckAttempt.study_session_id==study.id).limit(1)) or db.get(EnglishStudyState,study.id):
        reasons.append({"code":"TRAINING_HISTORY_PRESENT","message":"本轮有关联训练记录，不能从普通入口结束。"})
    return reasons


def latest_content(service, study):
    # No lease/commit in preview; restart owns the writer lease/transaction.
    from studyflow.infrastructure.runtime import Runtime
    from .service import LearningService
    reader=LearningService(Runtime(service.settings,service.session_factory,read_only=True))
    plan=json.loads(study.snapshot_json)["course"].get("plan_line_id")
    # Legacy /1 courses may use Course.plan_line_id without a PlanCourseItem.
    from studyflow.modules.planning.models import PlanCourseItem
    from studyflow.modules.courses.models import Course
    with reader.session(read_only=True) as db:
        member=db.scalar(select(PlanCourseItem.id).where(PlanCourseItem.course_id==study.course_id,PlanCourseItem.plan_line_id==plan)) if plan else None
        course=db.get(Course,study.course_id)
        legacy=not member and course and course.plan_line_id==plan
    if not member and not legacy:raise DomainError("SCOPE_MISMATCH","课程已不属于本轮冻结的计划。")
    result=capture(reader,study.course_id,plan if member else None)
    if json.loads(result[0])["course"].get("plan_line_id")!=plan:
        raise DomainError("SCOPE_MISMATCH","重开不能迁移旧轮次的计划归属。")
    return result


def preview(service, study_session_id):
    with service.session(read_only=True) as db:
        row=require_study(db,study_session_id,active=True)
        reasons=blockers(db,row)
        digest=None
        try:_,digest=latest_content(service,row)
        except (DomainError,OSError,UnicodeError):
            reasons.append({"code":"SOURCE_UNAVAILABLE","message":"最新版材料暂不可读；原轮次仍保留。"})
        return {"study_session_id":row.id,"course_id":row.course_id,"revision":row.revision,
            "expected_version":row.version,"expected_content_hash":digest,"frozen_content_hash":row.content_hash,
            "can_restart":not reasons,"blocked_reasons":reasons,
            "history_retained":True,"notes_retained":True,"reading_position_transferred":False}


def restart(service, study_session_id, expected_version, expected_content_hash, idempotency_key):
    if isinstance(expected_version,bool) or not isinstance(expected_version,int) or expected_version<1 or not isinstance(expected_content_hash,str) or len(expected_content_hash)!=64 or not isinstance(idempotency_key,str) or (not idempotency_key.strip() or not 1<=len(idempotency_key)<=160):
        raise DomainError("INVALID_ARGUMENT","重开需要预检查版本、内容哈希与稳定幂等键。")
    payload={"study_session_id":study_session_id,"expected_version":expected_version,"expected_content_hash":expected_content_hash}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    with service.session() as db:
        receipt=db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==idempotency_key))
        if receipt:
            if receipt.operation!="STUDY_RESTART" or receipt.payload_hash!=digest:
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT","重开幂等键已用于不同请求。")
            identifier=json.loads(receipt.result_json)["study_session_id"]
        else:
            if db.scalar(select(CourseStudySession.id).where(CourseStudySession.idempotency_key==idempotency_key)):
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已用于学习开始。")
            old=require_study(db,study_session_id,active=True)
            reasons=blockers(db,old)
            if reasons:raise DomainError("STUDY_RESTART_BLOCKED",reasons[0]["message"],"继续当前轮次；所有答案和笔记均保留。")
            if old.version!=expected_version:raise DomainError("VERSION_CONFLICT","阅读轮次已变化，请重新预检查。")
            text,content_hash=latest_content(service,old)
            if content_hash!=expected_content_hash:raise DomainError("COURSE_CONTENT_CONFLICT","最新版材料在确认期间已变化。","重新预检查并确认；旧轮次未结束。")
            changed=db.execute(update(CourseStudySession).where(CourseStudySession.id==old.id,
                CourseStudySession.version==expected_version,CourseStudySession.abandoned_at.is_(None)).values(
                abandoned_at=datetime.now(timezone.utc).replace(tzinfo=None),version=expected_version+1).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise DomainError("VERSION_CONFLICT","当前轮次已变化，未重开。")
            identifier=new_id()
            db.add(CourseStudySession(id=identifier,course_id=old.course_id,revision=old.revision+1,
                idempotency_key=idempotency_key,new_version=True,snapshot_json=text,content_hash=content_hash,
                progress_json="{}",version=1))
            db.flush()
            db.add(CourseWriteReceipt(id=new_id(),idempotency_key=idempotency_key,course_id=old.course_id,
                study_session_id=identifier,operation="STUDY_RESTART",payload_hash=digest,
                result_json=json.dumps({"study_session_id":identifier,"previous_study_session_id":old.id})))
            service._event(db,"USER_ENGINE","course_study",old.id,"ABANDON","明确保留历史并重新开始")
            service._event(db,"USER_ENGINE","course_study",identifier,"OPEN","用最新材料创建固定学习轮次")
            db.flush()
    return detail(service,identifier)

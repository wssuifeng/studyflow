"""Purpose-specific local reference reads, bound to immutable question snapshots."""
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from studyflow.shared.domain import DomainError
from studyflow.modules.learning.models import CourseStudySession,Submission,CourseReferenceView
from studyflow.modules.courses.models import CourseRevision
from studyflow.infrastructure.markdown import render_markdown
from .contract import fingerprint,reference_hash


def resolve(db,study_session_id=None,exercise_id=None,submission_id=None,reference_revision=None):
    if submission_id:
        if study_session_id or exercise_id:raise DomainError("INVALID_ARGUMENT","按submission或study/exercise二选一定位。")
        submission=db.get(Submission,submission_id)
        if not submission:raise DomainError("OBJECT_NOT_FOUND","作答不存在。")
        if submission.retest_task_id:return {"available":False,"reason":"独立复测题不复用原题解析，请读取复测任务依据。"}
        study_session_id=submission.study_session_id;exercise_id=submission.exercise_id
    if not study_session_id:return {"available":False,"reason":"旧作答没有冻结材料，不能推定参考版本。"}
    study=db.get(CourseStudySession,study_session_id)
    if not study or not exercise_id:raise DomainError("OBJECT_NOT_FOUND","需要有效轮次与题目定位。")
    content=json.loads(study.snapshot_json)
    question=next((ex for lesson in content["lessons"] for ex in lesson["exercises"] if ex["id"]==exercise_id),None)
    if question is None:raise DomainError("SCOPE_MISMATCH","题目不属于所选冻结轮次。")
    original_revision=content["course"].get("content_revision",1)
    revision=reference_revision if reference_revision is not None else original_revision
    if isinstance(revision,bool) or not isinstance(revision,int) or revision<1:raise DomainError("INVALID_ARGUMENT","参考版本须为正整数。")
    question_hash=fingerprint(question);reference=question.get("review_reference")
    if reference_revision is not None:
        record=db.scalar(select(CourseRevision).where(CourseRevision.course_id==study.course_id,CourseRevision.number==revision))
        if not record:raise DomainError("OBJECT_NOT_FOUND","参考课程版本不存在。")
        mapping=json.loads(record.mapping_json);package=json.loads(record.package_json)
        candidate=next((ex for lesson in package["lessons"] for ex in lesson.get("exercises",[]) if mapping["exercises"].get(lesson["id"]+":"+ex["id"])==exercise_id),None)
        if candidate is None or fingerprint(candidate)!=question_hash:raise DomainError("REFERENCE_MISMATCH","该参考版本与本轮冻结题面不一致；不会按同题ID猜测匹配。")
        reference=candidate.get("review_reference")
    if not reference:return {"available":False,"reason":"这道题尚未配置答案解析。","content_revision":revision,"question_hash":question_hash}
    digest=reference_hash(reference,question_hash)
    used=db.scalar(select(CourseReferenceView.study_session_id).where(CourseReferenceView.study_session_id==study.id,CourseReferenceView.exercise_id==exercise_id).limit(1)) is not None
    rendered={key:render_markdown(reference[key]) for key in ("answer","explanation")}
    return {"available":True,"study_session_id":study.id,"exercise_id":exercise_id,"course_id":study.course_id,"content_revision":revision,"frozen_content_revision":original_revision,"question_hash":question_hash,"reference_hash":digest,"reference":reference,"rendered":rendered,"is_correction":revision!=original_revision,"hint_used":used,"hint_information":"recorded_since_1.8" if study.hint_tracking_enabled else "legacy_unknown"}


def read_reference(service,**params):
    with service.session(read_only=True) as db:return resolve(db,**params)


def view_reference(service,**params):
    with service.session() as db:
        result=resolve(db,**params)
        if result.get("available"):
            key=(result["study_session_id"],result["exercise_id"],result["reference_hash"])
            if not db.get(CourseReferenceView,key):
                try:
                    with db.begin_nested():
                        db.add(CourseReferenceView(study_session_id=key[0],exercise_id=key[1],reference_hash=key[2]));db.flush()
                except IntegrityError:
                    if not db.get(CourseReferenceView,key):raise
                service._event(db,"USER_ENGINE","course_study",key[0],"VIEW_REFERENCE",key[1])
            result["hint_used"]=True
        return result

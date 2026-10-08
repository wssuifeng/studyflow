"""Explicit Agent-authored, frozen retests. Never infer a question from prose."""
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.learning.models import Submission
from studyflow.modules.learning.write_contract import digest
from .models import RetestTask

def public_task(row):
    return {k:getattr(row,k) for k in ("id","parent_submission_id","study_session_id","title","prompt","requirements","objective","status")}

def publish(service, parent_submission_id, title, prompt, objective, idempotency_key, requirements="", agent_reference=""):
    values={"parent_submission_id":parent_submission_id,"title":title,"prompt":prompt,"requirements":requirements,"objective":objective,"agent_reference":agent_reference}
    for key,value in values.items():
        if not isinstance(value,str) or (key not in {"requirements","agent_reference"} and not value.strip()) or len(value)>20000:
            raise DomainError("INVALID_ARGUMENT",f"{key}必须为有效文本，最多20000字符。")
    if len(title)>200: raise DomainError("INVALID_ARGUMENT","title最多200字符。")
    if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160: raise DomainError("INVALID_ARGUMENT","需要稳定幂等键。")
    with service.session() as db:
        old=db.scalar(select(RetestTask).where(RetestTask.idempotency_key==idempotency_key))
        if old:
            if old.payload_hash!=digest(values): raise DomainError("IDEMPOTENCY_KEY_CONFLICT","此复测幂等键已用于其他题面。")
            return public_task(old)
        parent=db.get(Submission,parent_submission_id)
        if not parent or parent.status!="RETEST_REQUIRED": raise DomainError("INVALID_ATTEMPT_SOURCE","仅可为待复测答案发布题目。")
        if db.scalar(select(Submission.id).where(Submission.parent_submission_id==parent.id)) or db.scalar(select(RetestTask.id).where(RetestTask.parent_submission_id==parent.id)):
            raise DomainError("VERSION_CONFLICT","已有后续版本或已发布复测，不能静默换题。")
        row=RetestTask(id=new_id(),study_session_id=parent.study_session_id,idempotency_key=idempotency_key,payload_hash=digest(values),**values)
        db.add(row);db.flush();service._event(db,"AGENT_CLI","retest",row.id,"PUBLISH","发布冻结复测题面")
        return public_task(row)

def validate_issues(answer,issues):
    if issues is None:return None
    if not isinstance(issues,list) or len(issues)>50:raise DomainError("INVALID_ARGUMENT","issues必须是最多50项的数组。")
    fields={"quote","location","reason","guidance","next_action"}
    for i,issue in enumerate(issues):
        if not isinstance(issue,dict) or set(issue)!=fields or any(not isinstance(v,str) or not v.strip() or len(v)>10000 for v in issue.values()):raise DomainError("INVALID_ARGUMENT",f"issues[{i}]需要quote/location/reason/guidance/next_action。")
        if issue["quote"] not in answer:raise DomainError("REVIEW_QUOTE_MISMATCH",f"issues[{i}].quote不在原答案中。","引用对应答案原句，不要编造。")
    return issues

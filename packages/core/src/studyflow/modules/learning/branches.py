"""Explicitly select an effective legacy branch without removing any evidence."""
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from .models import Submission, SubmissionChainLink

def resolve(service,parent_submission_id,child_submission_id,reason):
    if not isinstance(reason,str) or not reason.strip():raise DomainError("INVALID_ARGUMENT","选择有效分支必须填写审计原因。")
    with service.session() as db:
        children=list(db.scalars(select(Submission).where(Submission.parent_submission_id==parent_submission_id)))
        if len(children)<2 or child_submission_id not in {c.id for c in children}:raise DomainError("INVALID_ARGUMENT","只能解决确实存在且属于父答案的历史分叉。")
        old=db.get(SubmissionChainLink,parent_submission_id)
        if old:
            if old.child_id==child_submission_id:return {"ok":True,"parent_submission_id":parent_submission_id,"child_submission_id":child_submission_id,"replayed":True}
            raise DomainError("VERSION_CONFLICT","此分叉已选择有效分支，不能无声覆盖。")
        db.add(SubmissionChainLink(parent_id=parent_submission_id,child_id=child_submission_id,source="AGENT_CLI",reason=reason))
        service._event(db,"AGENT_CLI","submission",parent_submission_id,"RESOLVE_BRANCH",reason)
        return {"ok":True,"parent_submission_id":parent_submission_id,"child_submission_id":child_submission_id,"replayed":False}

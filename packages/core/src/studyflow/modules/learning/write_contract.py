"""Shared write receipts and chain CAS, independent of UI/CLI adapters."""
import hashlib
import json
from sqlalchemy import select, update
from studyflow.shared.domain import DomainError
from .models import Submission, SubmissionChainLink, SubmissionWriteReceipt
from studyflow.shared.ids import new_id

FIELDS = ("id", "exercise_id", "task_id", "parent_submission_id", "study_session_id", "batch_id", "answer_text", "status", "source", "version", "attempt_number", "attempt_kind", "next_action", "idempotency_key")

def digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def replay(db,key,operation,payload):
    if key is None: return None
    if not isinstance(key,str) or not key.strip() or len(key)>160:
        raise DomainError("INVALID_ARGUMENT","幂等键必须是1—160字符文本。")
    receipt=db.scalar(select(SubmissionWriteReceipt).where(SubmissionWriteReceipt.idempotency_key==key))
    if not receipt:
        legacy=db.scalar(select(Submission).where(Submission.idempotency_key==key))
        if legacy: raise DomainError("IDEMPOTENCY_UNVERIFIABLE","旧回执没有请求hash，无法验证重试。","回读原答案，不要自动重新提交。")
        return None
    if not receipt.payload_hash or not receipt.result_json:
        raise DomainError("IDEMPOTENCY_UNVERIFIABLE","旧回执没有请求hash，无法验证重试。","回读原答案，不要自动重新提交。")
    if receipt.operation!=operation or receipt.payload_hash!=digest(payload):
        raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已用于不同的作答载荷。","只对完全相同的请求使用原幂等键。")
    return Submission(**json.loads(receipt.result_json))

def record(db,key,operation,payload,row):
    if key:
        db.add(SubmissionWriteReceipt(id=new_id(),idempotency_key=key,operation=operation,submission_id=row.id,payload_hash=digest(payload),result_json=json.dumps({f:getattr(row,f) for f in FIELDS},ensure_ascii=False)))
        db.flush()

def claim_parent(db,parent,child_id,source):
    children=list(db.scalars(select(Submission.id).where(Submission.parent_submission_id==parent.id)))
    if children or db.get(SubmissionChainLink,parent.id):
        raise DomainError("VERSION_CONFLICT","父作答已有后续版本。","回读课程同轮答案，不要重复创建修正版。")
    version=parent.version
    changed=db.execute(update(Submission).where(Submission.id==parent.id,Submission.version==version).values(version=version+1).execution_options(synchronize_session=False))
    if changed.rowcount!=1:
        raise DomainError("VERSION_CONFLICT","父作答版本已变化。","回读当前有效答案。")
    # FK is satisfied by the caller after inserting the child in this transaction.
    db.add(SubmissionChainLink(parent_id=parent.id,child_id=child_id,source=source))

def effective_rows(db,rows):
    by_parent={}
    for row in rows:
        if row.parent_submission_id: by_parent.setdefault(row.parent_submission_id,[]).append(row)
    excluded=set()
    for parent,children in by_parent.items():
        if len(children)>1:
            link=db.get(SubmissionChainLink,parent)
            if not link:
                raise DomainError("SUBMISSION_BRANCH_CONFLICT","历史作答存在分叉，已保留全部记录并暂停写入。","使用submission.resolve-branch显式选择有效分支并填写原因。")
            excluded.update(child.id for child in children if child.id!=link.child_id)
    changed=True
    while changed:
        changed=False
        for row in rows:
            if row.parent_submission_id in excluded and row.id not in excluded: excluded.add(row.id);changed=True
    return [row for row in rows if row.id not in excluded]

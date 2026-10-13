import hashlib,json
from sqlalchemy import select
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate,EnglishReviewItem
from studyflow.modules.mistakes.general.models import GeneralMistakeEntry
from studyflow.shared.domain import DomainError


def snapshot(service,db,scope):
    query,domain,_=service._query(db,**scope)
    model=EnglishErrorAggregate if domain=="english" else GeneralMistakeEntry
    rows=list(db.scalars(query.order_by(model.id).limit(1001)))
    if len(rows)>1000:raise DomainError("SCOPE_TOO_LARGE","每次归档最多1000条，请缩小课程/时间范围。")
    if domain=="english":
        blocked=db.scalar(select(EnglishReviewItem.id).where(EnglishReviewItem.aggregate_id.in_([r.id for r in rows]),EnglishReviewItem.status.in_(["PENDING","RETESTING"])).limit(1))
    else:blocked=any(r.status!="PASSED" for r in rows)
    if blocked:raise DomainError("ACTIVE_TASK_PROTECTED","范围内仍有待修正/复测任务，不允许归档。")
    payload={"scope":scope,"rows":[{"id":r.id,"version":r.version} for r in rows]}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return rows,{"count":len(rows),"preview_hash":digest,"logical_only":True}

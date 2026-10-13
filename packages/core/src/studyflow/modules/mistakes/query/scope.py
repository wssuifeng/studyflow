from sqlalchemy import select
from studyflow.modules.mistakes.query.models import MistakeNotebook
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id

def notebook(db,plan_line_id,domain,create=False):
    if domain not in {"general","english"}:raise DomainError("INVALID_ARGUMENT","未知错误领域。")
    scope="plan:"+plan_line_id if plan_line_id else "unassigned"
    row=db.scalar(select(MistakeNotebook).where(MistakeNotebook.scope_key==scope,MistakeNotebook.domain==domain))
    if row is None and create:
        row=MistakeNotebook(id=new_id(),scope_key=scope,plan_line_id=plan_line_id,domain=domain);db.add(row);db.flush()
    return row

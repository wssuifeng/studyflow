from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from studyflow.shared.domain import DomainError

class QueueRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    role: Literal["agent","learner","all"]="all"
    plan_line_id: str|None=None
    course_id: str|None=None
    status: str|None=None
    cursor: str|None=None
    limit: int=Field(default=50,ge=1,le=100)
    history: bool=False
class RetestRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    parent_submission_id: str
    title: str=Field(min_length=1,max_length=200)
    prompt: str=Field(min_length=1,max_length=20000)
    objective: str=Field(min_length=1,max_length=20000)
    requirements: str=""
    agent_reference: str=""
    idempotency_key: str=Field(min_length=1,max_length=160)

class Request(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
class ContextRequest(Request):
    submission_ids:list[str]=Field(min_length=1,max_length=100)
class UpdatePreviewRequest(Request):
    course_id:str=Field(min_length=1)
    path:str=Field(min_length=1)
    expected_revision:int=Field(ge=1)
class UpdateApplyRequest(UpdatePreviewRequest):
    preview_hash:str=Field(pattern="^[a-f0-9]{64}$")
    idempotency_key:str=Field(min_length=1,max_length=160)
class PlanEditRequest(Request):
    plan_line_id:str=Field(min_length=1)
    expected_version:int=Field(ge=1)
    idempotency_key:str=Field(min_length=1,max_length=160)
    operation:Literal["UPDATE","REORDER","SCHEDULE","RESCHEDULE","CANCEL_SCHEDULE"]
    values:dict
class PlanRequest(Request):
    plan_line_id:str=Field(min_length=1)
class NotebookSearchRequest(PlanRequest):
    query:str=Field(default="",max_length=200)
    course_id:str|None=None
    lesson_id:str|None=None
class SourceRequest(Request):
    study_session_id:str=Field(min_length=1)
    lesson_id:str=Field(min_length=1)
    block_id:str|None=None
class BackupRequest(Request):
    path:str=Field(min_length=1)
class RestoreRequest(BackupRequest):
    target_root:str=Field(min_length=1)
class BranchRequest(Request):
    parent_submission_id:str=Field(min_length=1)
    child_submission_id:str=Field(min_length=1)
    reason:str=Field(min_length=1,max_length=10000)
class Issue(Request):
    quote:str=Field(min_length=1,max_length=10000)
    location:str=Field(min_length=1,max_length=10000)
    reason:str=Field(min_length=1,max_length=10000)
    guidance:str=Field(min_length=1,max_length=10000)
    next_action:str=Field(min_length=1,max_length=10000)
class ReviewRequest(Request):
    submission_id:str=Field(min_length=1)
    summary:str=Field(min_length=1)
    detail_markdown:str=""
    issue_count:int=Field(default=0,ge=0)
    needs_revision:bool=False
    idempotency_key:str|None=None
    source:str="AGENT_CLI"
    decision:str|None=None
    next_action:str=""
    issues:list[Issue]|None=None
SCHEMAS={"assignment.summary":QueueRequest,"assignment.context":ContextRequest,"review.retest.publish":RetestRequest,"review.write":ReviewRequest,"course.update.preview":UpdatePreviewRequest,"course.update.apply":UpdateApplyRequest,"plan.edit":PlanEditRequest,"plan.schedule.list":PlanRequest,"plan.notebook.search":NotebookSearchRequest,"plan.notebook.export":PlanRequest,"course.source.read":SourceRequest,"workspace.export":BackupRequest,"workspace.validate":BackupRequest,"workspace.restore":RestoreRequest,"submission.resolve-branch":BranchRequest}

def validate(method,params):
    from pydantic import ValidationError
    if method not in SCHEMAS:return params
    try:return SCHEMAS[method].model_validate(params).model_dump()
    except ValidationError as exc:
        errors=[{"path":".".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors()]
        raise DomainError("INVALID_ARGUMENT",str(errors),"先读取system.schema，按错误路径修正字段。") from exc

def schemas(method=None):
    if method and method not in SCHEMAS:raise DomainError("METHOD_NOT_FOUND","没有此方法的结构化schema。")
    return {"schema_version":"studyflow.agent-contract/2","methods":{k:v.model_json_schema() for k,v in SCHEMAS.items() if not method or k==method}}

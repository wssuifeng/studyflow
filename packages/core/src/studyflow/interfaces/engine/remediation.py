"""Neutral transport contract for supplemental English courses."""
from pydantic import Field
from .schemas import Request
class Source(Request):
    aggregate_id:str=Field(min_length=1,max_length=100)
    expected_version:int=Field(ge=1)
    evidence_ids:list[str]=Field(min_length=1,max_length=10)
class PreviewRequest(Request):
    plan_line_id:str=Field(min_length=1)
    path:str=Field(min_length=1)
    objective_ids:list[str]=Field(min_length=1,max_length=5)
    rationale:str=Field(min_length=1,max_length=4000)
    sources:list[Source]=Field(min_length=1,max_length=30)
class PublishRequest(PreviewRequest):
    preview_hash:str=Field(pattern="^[a-f0-9]{64}$")
    idempotency_key:str=Field(min_length=1,max_length=160)
class ListRequest(Request):
    plan_line_id:str=Field(min_length=1)
    source_course_id:str|None=None
    aggregate_id:str|None=None
    limit:int=Field(default=30,ge=1,le=100)
    offset:int=Field(default=0,ge=0,le=100000)
class GetRequest(Request):
    course_id:str=Field(min_length=1)
SCHEMAS={"course.remediation.preview":PreviewRequest,"course.remediation.publish":PublishRequest,"course.remediation.list":ListRequest,"course.remediation.get":GetRequest}
METHODS={name:"write" if name.endswith("publish") else "read" for name in SCHEMAS}
def dispatch(engine,method,params):
    return getattr(engine.service.remediation,method.rsplit(".",1)[1])(**params)

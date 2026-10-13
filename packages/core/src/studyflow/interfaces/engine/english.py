"""English and error-management transport schema; all rules stay in Core."""
from typing import Literal
from pydantic import Field
from .schemas import Request

class EnglishStudyRequest(Request):
    study_session_id:str=Field(min_length=1)
class EnglishItemRequest(EnglishStudyRequest):
    exercise_id:str=Field(min_length=1)
class EnglishSaveRequest(EnglishItemRequest):
    answer_text:str=Field(max_length=4000)
    expected_version:int=Field(ge=0)
    idempotency_key:str=Field(min_length=1,max_length=160)
    skipped:bool=False
class EnglishCheckRequest(EnglishItemRequest):
    expected_version:int=Field(ge=1)
    idempotency_key:str=Field(min_length=1,max_length=160)
class EnglishRevealRequest(EnglishItemRequest):
    idempotency_key:str=Field(min_length=1,max_length=160)
class EnglishSubmitRequest(EnglishStudyRequest):
    idempotency_key:str=Field(min_length=1,max_length=160)
    expected_versions:dict[str,int]
class EnglishMoveRequest(EnglishStudyRequest):
    position:int=Field(ge=0,le=499)
    expected_version:int=Field(ge=0)
    idempotency_key:str=Field(min_length=1,max_length=160)
class ScopeRequest(Request):
    notebook_id:str|None=None
    plan_line_id:str|None=None
    domain:Literal["general","english"]|None=None
    course_id:str|None=None
    archived:bool=False
    objective_id:str|None=None
    since:str|None=None
    until:str|None=None
    view:Literal["training_errors","review_queue"]="training_errors"
class MistakeListRequest(ScopeRequest):
    cursor:str|None=None
    limit:int=Field(default=30,ge=1,le=100)
class MistakeContextRequest(MistakeListRequest):
    identifier:str=Field(min_length=1)
    expected_version:int|None=Field(default=None,ge=1)
class MistakeSelectRequest(ScopeRequest):
    idempotency_key:str=Field(min_length=1,max_length=160)
    identifier:str=Field(min_length=1)
    expected_version:int=Field(ge=1)
class DictionaryRequest(EnglishItemRequest):
    word_index:int|None=Field(default=None,ge=0,le=79)
    accent:Literal["en-US","en-GB"]="en-US"

class RetestGetRequest(Request):
    task_id:str=Field(min_length=1)
class RetestCheckRequest(RetestGetRequest):
    answer_text:str=Field(min_length=1,max_length=4000)
    idempotency_key:str=Field(min_length=1,max_length=160)
    expected_version:int=Field(ge=0)
class RetestSaveRequest(RetestGetRequest):
    answer_text:str=Field(max_length=4000)
    expected_version:int=Field(ge=0)
    idempotency_key:str=Field(min_length=1,max_length=160)
class MistakeRetestRequest(MistakeSelectRequest):
    idempotency_key:str=Field(min_length=1,max_length=160)
class ArchiveApplyRequest(ScopeRequest):
    idempotency_key:str=Field(min_length=1,max_length=160)
    preview_hash:str=Field(pattern="^[a-f0-9]{64}$")

SCHEMAS={"course.english.get":EnglishStudyRequest,"course.english.save":EnglishSaveRequest,"course.english.check":EnglishCheckRequest,"course.english.reveal":EnglishRevealRequest,"course.english.answer":EnglishItemRequest,"course.english.submit":EnglishSubmitRequest,"course.english.navigate":EnglishMoveRequest,"course.english.request-review":EnglishCheckRequest,"mistakes.notebooks":Request,"mistakes.summary":ScopeRequest,"mistakes.list":MistakeListRequest,"mistakes.context":MistakeContextRequest,"mistakes.english.review.select":MistakeSelectRequest,"audio.dictionary.lookup":DictionaryRequest}
SCHEMAS.update({"course.english.retest-get":RetestGetRequest,"course.english.retest-save":RetestSaveRequest,"course.english.retest-check":RetestCheckRequest,"mistakes.retest.request":MistakeRetestRequest,"mistakes.archive.preview":ScopeRequest,"mistakes.archive.apply":ArchiveApplyRequest})
WRITES={"course.english.save","course.english.check","course.english.reveal","course.english.submit","course.english.navigate","course.english.request-review","mistakes.english.review.select"}
WRITES.update({"course.english.retest-save","course.english.retest-check","mistakes.retest.request","mistakes.archive.apply"})
METHODS={name:"write" if name in WRITES else "read" for name in SCHEMAS}

def dispatch(engine,method,params):
    if method.startswith("course.english."):
        action=method.removeprefix("course.english.").replace("-","_")
        return getattr(engine.service.english,action)(**params)
    if method.startswith("mistakes."):
        action={"mistakes.english.review.select":"select_review","mistakes.retest.request":"retest_request","mistakes.archive.preview":"archive_preview","mistakes.archive.apply":"archive_apply"}.get(method,method.removeprefix("mistakes."))
        return getattr(engine.service.mistakes,action)(**params)
    return engine.service.audio.lookup(**params)

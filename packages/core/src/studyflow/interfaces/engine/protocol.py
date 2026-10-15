from __future__ import annotations

import re
from typing import Any
from sqlalchemy.exc import SQLAlchemyError

from studyflow import __version__
from studyflow.config import Settings
from studyflow.shared.domain import DomainError

PROTOCOL_VERSION = "1.2"

CAPABILITIES: list[dict[str, str]] = [
    {"name":"course_update_preview","method":"course.update.preview","kind":"read"},
    {"name":"course_update_apply","method":"course.update.apply","kind":"write"},
    {"name":"assignment_summary","method":"assignment.summary","kind":"read"},
    {"name":"assignment_context","method":"assignment.context","kind":"read"},
    {"name":"retest_publish","method":"review.retest.publish","kind":"write"},
    {"name":"system_changes","method":"system.changes","kind":"read"},
    {"name":"system_schema","method":"system.schema","kind":"read"},
    {"name":"plan_notebook_get","method":"plan.notebook.get","kind":"read"},
    {"name":"plan_notebook_save","method":"plan.notebook.save","kind":"write"},
    {"name": "version", "method": "system.version", "kind": "read"},
    {"name": "capabilities", "method": "system.capabilities", "kind": "read"},
    {"name": "doctor", "method": "system.doctor", "kind": "diagnostic"},
    {"name": "today", "method": "study.today", "kind": "read"},
    {"name": "assignment_queue", "method": "assignment.queue", "kind": "read"},
    {"name": "plan_list", "method": "plan.list", "kind": "read"},
    {"name": "plan_detail", "method": "plan.detail", "kind": "read"},
    {"name": "course_list", "method": "course.list", "kind": "read"},
    {"name": "course_detail", "method": "course.detail", "kind": "read"},
    {"name": "course_study_open", "method": "course.study.open", "kind": "write"},
    {"name": "course_study_get", "method": "course.study.get", "kind": "read"},
    {"name": "course_study_progress_save", "method": "course.study.progress.save", "kind": "write"},
    {"name": "course_study_reading_complete", "method": "course.study.reading.complete", "kind": "write"},
    {"name": "course_answers_get", "method": "course.answers.get", "kind": "read"},
    {"name": "course_answers_draft_save", "method": "course.answers.draft.save", "kind": "write"},
    {"name": "course_answers_submit", "method": "course.answers.submit", "kind": "write"},
    {"name": "course_notes_get", "method": "course.notes.get", "kind": "read"},
    {"name": "course_notes_save", "method": "course.notes.save", "kind": "write"},
    {"name": "document_read", "method": "document.read", "kind": "read"},
    {"name": "submission_get", "method": "submission.get", "kind": "read"},
    {"name": "submission_draft_save", "method": "submission.draft.save", "kind": "write"},
    {"name": "submission_submit", "method": "submission.submit", "kind": "write"},
    {"name": "learning_progress_save", "method": "learning.progress.save", "kind": "write"},
    {"name": "course_import", "method": "course.import", "kind": "write"},
    {"name": "review_write", "method": "review.write", "kind": "write"},
    {"name": "submission_revise", "method": "submission.revise", "kind": "write"},
    {"name": "submission_retest", "method": "submission.retest", "kind": "write"},
    {"name": "snapshot_generate", "method": "snapshot.generate", "kind": "write"},
]


from .english import METHODS as ENGLISH_METHODS
CAPABILITIES.extend({"name":method.replace(".","_").replace("-","_"),"method":method,"kind":kind} for method,kind in ENGLISH_METHODS.items())

_CREDENTIAL_URL = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:/\s]+:)([^@/\s]+)(@)", re.IGNORECASE)
_SENSITIVE_QUERY = re.compile(r"(?i)([?&](?:password|passwd|pwd|secret|token)=)[^&\s]+")


def redact_sensitive_text(value: str) -> str:
    """Prevent credentials from crossing the Engine JSON boundary."""
    value = _CREDENTIAL_URL.sub(r"\1***\3", value)
    return _SENSITIVE_QUERY.sub(r"\1***", value)


def error_payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, DomainError):
        return {"code": error.code, "error_code": error.code,
                "message": redact_sensitive_text(error.message),
                "next_action": redact_sensitive_text(error.next_action) or "重新读取当前对象状态后重试。"}
    from studyflow.infrastructure.errors import database_error_payload
    database_error = database_error_payload(error)
    if database_error:
        return {**database_error, "error_code":database_error["code"]}
    if isinstance(error, OSError):
        return {"code": "FILESYSTEM_ERROR", "error_code": "FILESYSTEM_ERROR", "message": "工作区文件操作失败。",
                "next_action": "检查工作区文件状态和读取权限后重试。"}
    return {"code": "INTERNAL_ERROR", "error_code": "INTERNAL_ERROR", "message": "Engine 内部错误。",
            "next_action": "检查 Engine 日志或先运行 system.doctor。"}


def make_response(request_id: Any, data: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {"id": request_id, "ok": error is None}
    if error is None:
        response["data"] = data
    else:
        response["error"] = error
    return response


def discovery_metadata(settings: Settings) -> dict[str, Any]:
    return {
        "workspace": {"root": str(settings.workspace_root), "exists": settings.workspace_root.is_dir()},
        "database": {"driver": settings.database_url.split(":", 1)[0], "managed_by_app": settings.database_url.startswith("sqlite"), "status": "engine_managed"},
    }


def all_capabilities():
    from .extensions import METHODS
    existing={i["method"] for i in CAPABILITIES}
    return CAPABILITIES+[{"name":m.replace(".","_"),"method":m,"kind":kind} for m,kind in METHODS.items() if m not in existing]

def version_payload(settings: Settings) -> dict[str, Any]:
    return {"protocol_version": PROTOCOL_VERSION, "app_version": __version__, **discovery_metadata(settings), "capabilities": [item["name"] for item in all_capabilities()], "next_action": "调用 system.doctor 检查工作区与数据库。"}


def content_capabilities():
    from studyflow.modules.courses.content import SCHEMA, ENGLISH_SCHEMA, DETAILS_SCHEMA, PROGRESSION_SCHEMA, STRUCTURED_SCHEMA, ENGLISH_TRAINING_SCHEMA, BLOCK_TYPES
    return {"notebook": {"formats":[1,2], "write_method":"plan.notebook.apply", "read_method":"plan.notebook.read", "read_limit":100, "max_entries":1000, "immutable_sources":True, "legacy_write_v2":False}, "course_package_schemas": [SCHEMA, ENGLISH_SCHEMA, DETAILS_SCHEMA, PROGRESSION_SCHEMA, STRUCTURED_SCHEMA, ENGLISH_TRAINING_SCHEMA], "learning_modes": ["general", "english"], "structured_sections":{"schema":STRUCTURED_SCHEMA,"max_depth":2,"max_sections":40,"max_body_chars":20000,"roles":["main","supplement"]},"review_reference":{"schema":STRUCTURED_SCHEMA,"fields":["answer","explanation","criteria","accepted_variants","source"],"read_method":"exercise.reference.read","view_method":"exercise.reference.view","default_folded":True,"account_permissions":False},"plan_course_groups":{"groups":["PENDING","COMPLETED","OTHER"],"edit_operation":"COURSE_POSITION","scope":"plan_course_item"},"learning_evidence":{"method":"learning.evidence","max_limit":100,"infers_mastery":False},
            "teaching_block_types": sorted(BLOCK_TYPES), "details": {"schema":DETAILS_SCHEMA,"required_fields":["id","type","title","summary","body"],"max_chars":{"title":200,"summary":3000,"body":20000},"nested_blocks":False,"default_expanded":False},
            "schema_block_types":{SCHEMA:sorted(BLOCK_TYPES-{"details"}),ENGLISH_SCHEMA:sorted(BLOCK_TYPES-{"details"}),DETAILS_SCHEMA:sorted(BLOCK_TYPES),PROGRESSION_SCHEMA:sorted(BLOCK_TYPES),STRUCTURED_SCHEMA:sorted(BLOCK_TYPES),ENGLISH_TRAINING_SCHEMA:sorted(BLOCK_TYPES)}, "progression":{"schema":PROGRESSION_SCHEMA,"fields":["chain_id","stage"],"stages":["vocabulary","chunk","pattern","variation","transfer"],"supplement_requires":["vocabulary","pattern","transfer"],"original_errors_auto_resolved":False}, "english": {"evaluation_modes": ["local_exact", "agent"], "training_schema":ENGLISH_TRAINING_SCHEMA, "training_evaluation_modes":["local_exact"], "variable_length_variants":True, "sentence_parts":True,
            "max_items_per_course": 500, "max_tokens_per_item": 80, "audio_default": "dictionary",
            "tts_generation": False, "english_detached_editor": False}}


def capabilities_payload(settings: Settings) -> dict[str, Any]:
    return {"protocol_version": PROTOCOL_VERSION, "app_version": __version__, **discovery_metadata(settings), "capabilities": all_capabilities(), "content": content_capabilities(), "next_action": "调用 system.doctor，再按当前任务选择方法。"}

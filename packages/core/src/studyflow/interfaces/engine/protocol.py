from __future__ import annotations

import re
from typing import Any
from sqlalchemy.exc import SQLAlchemyError

from studyflow import __version__
from studyflow.config import Settings
from studyflow.shared.domain import DomainError

PROTOCOL_VERSION = "1.2"

CAPABILITIES: list[dict[str, str]] = [
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
    if isinstance(error, SQLAlchemyError):
        return {"code": "DATABASE_ERROR", "error_code": "DATABASE_ERROR", "message": "数据库操作失败，当前请求未完成。",
                "next_action": "运行 doctor 检查数据库；写入重试请使用原幂等键。"}
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


def version_payload(settings: Settings) -> dict[str, Any]:
    return {"protocol_version": PROTOCOL_VERSION, "app_version": __version__, **discovery_metadata(settings), "capabilities": [item["name"] for item in CAPABILITIES], "next_action": "调用 system.doctor 检查工作区与数据库。"}


def capabilities_payload(settings: Settings) -> dict[str, Any]:
    return {"protocol_version": PROTOCOL_VERSION, "app_version": __version__, **discovery_metadata(settings), "capabilities": CAPABILITIES, "next_action": "调用 system.doctor，再按当前任务选择方法。"}

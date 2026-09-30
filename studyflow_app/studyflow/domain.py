from __future__ import annotations

from dataclasses import dataclass

TASK_KINDS = {"READING", "PRACTICE", "EXAM", "PROJECT", "REVIEW", "DOCUMENT", "OTHER"}
COURSE_CONTENT_TYPES = {"LESSON", "REFERENCE", "EXAM_PREP", "PROJECT_GUIDE", "REVIEW", "OTHER"}
EXERCISE_TYPES = {"SHORT_ANSWER", "CODE", "ESSAY", "EXAM_QUESTION", "CHECKLIST", "SELF_EXPLANATION", "PROJECT_ANALYSIS", "OTHER"}
DOCUMENT_TYPES = {"LESSON", "REVIEW", "PROJECT", "PLAN", "SNAPSHOT", "REFERENCE", "ANSWER", "FEEDBACK", "OTHER", "MARKDOWN"}

TASK_STATUSES = {"TODO", "IN_PROGRESS", "PARTIAL", "DONE", "DEFERRED", "BLOCKED", "CANCELLED", "ARCHIVED"}
SUBMISSION_STATUSES = {"DRAFT", "SUBMITTED", "WAITING_REVIEW", "REVIEWED", "NEEDS_REVISION", "RESUBMITTED", "RECHECKED", "PASSED", "RETEST_REQUIRED"}
REVIEW_DECISIONS = {"PASSED", "REVISION_REQUIRED", "RETEST_REQUIRED"}
ATTEMPT_KINDS = {"FIRST", "REVISION", "RETEST"}

TASK_TRANSITIONS = {
    "TODO": {"IN_PROGRESS", "DEFERRED", "BLOCKED", "CANCELLED"},
    "IN_PROGRESS": {"PARTIAL", "DONE", "DEFERRED", "BLOCKED", "CANCELLED"},
    "PARTIAL": {"IN_PROGRESS", "DONE", "DEFERRED", "BLOCKED"},
    "DEFERRED": {"TODO", "IN_PROGRESS", "CANCELLED"},
    "BLOCKED": {"TODO", "IN_PROGRESS", "CANCELLED"},
    "DONE": {"ARCHIVED"},
    "CANCELLED": {"ARCHIVED"},
    "ARCHIVED": set(),
}

SUBMISSION_TRANSITIONS = {
    "DRAFT": {"DRAFT", "SUBMITTED", "WAITING_REVIEW"},
    "SUBMITTED": {"WAITING_REVIEW"},
    "WAITING_REVIEW": {"REVIEWED", "NEEDS_REVISION", "PASSED", "RETEST_REQUIRED"},
    "REVIEWED": {"NEEDS_REVISION", "RECHECKED", "PASSED", "RETEST_REQUIRED"},
    "NEEDS_REVISION": {"RESUBMITTED"},
    "RESUBMITTED": {"WAITING_REVIEW"},
    "RETEST_REQUIRED": {"RESUBMITTED"},
    "RECHECKED": {"RECHECKED"},
    "PASSED": {"PASSED"},
}


@dataclass
class DomainError(Exception):
    code: str
    message: str
    next_action: str = ""

    def __str__(self) -> str:
        return self.message


def validate_task_transition(current: str, target: str, reason: str = "", next_action: str = "") -> None:
    if target not in TASK_STATUSES:
        raise DomainError("INVALID_STATUS", f"未知任务状态: {target}")
    if target == current:
        return
    if target not in TASK_TRANSITIONS.get(current, set()):
        raise DomainError("INVALID_STATE_TRANSITION", f"任务不能从 {current} 转为 {target}")
    if target in {"DEFERRED", "BLOCKED"} and (not reason.strip() or not next_action.strip()):
        raise DomainError("REASON_REQUIRED", "延期或阻塞必须填写原因和下一动作")


def validate_submission_status(current: str, target: str) -> None:
    if target not in SUBMISSION_STATUSES:
        raise DomainError("INVALID_STATUS", f"未知作答状态: {target}")
    if target not in SUBMISSION_TRANSITIONS.get(current, set()):
        raise DomainError("INVALID_STATE_TRANSITION", f"作答不能从 {current} 转为 {target}")


def normalize_review_decision(decision: str | None, needs_revision: bool = False) -> str:
    if decision is None or not decision.strip():
        return "REVISION_REQUIRED" if needs_revision else "PASSED"
    normalized = decision.strip().upper()
    aliases = {"REVIEWED": "PASSED", "NEEDS_REVISION": "REVISION_REQUIRED", "RETEST": "RETEST_REQUIRED"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in REVIEW_DECISIONS:
        raise DomainError("INVALID_REVIEW_DECISION", f"未知批改决定: {decision}", f"可用决定：{', '.join(sorted(REVIEW_DECISIONS))}")
    return normalized

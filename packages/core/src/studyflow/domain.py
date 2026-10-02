"""Compatibility import; implementation lives in studyflow.shared.domain."""
from studyflow.shared.domain import DomainError, validate_task_transition, validate_submission_status, normalize_review_decision, TASK_KINDS, COURSE_CONTENT_TYPES, EXERCISE_TYPES, DOCUMENT_TYPES, TASK_STATUSES, SUBMISSION_STATUSES, REVIEW_DECISIONS, ATTEMPT_KINDS, TASK_TRANSITIONS, SUBMISSION_TRANSITIONS

__all__ = ['DomainError', 'validate_task_transition', 'validate_submission_status', 'normalize_review_decision', 'TASK_KINDS', 'COURSE_CONTENT_TYPES', 'EXERCISE_TYPES', 'DOCUMENT_TYPES', 'TASK_STATUSES', 'SUBMISSION_STATUSES', 'REVIEW_DECISIONS', 'ATTEMPT_KINDS', 'TASK_TRANSITIONS', 'SUBMISSION_TRANSITIONS']

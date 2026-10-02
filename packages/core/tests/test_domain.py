from studyflow.domain import DomainError, validate_submission_status, validate_task_transition


def test_blocked_task_requires_reason_and_next_action():
    try:
        validate_task_transition("TODO", "BLOCKED")
    except DomainError as exc:
        assert exc.code == "REASON_REQUIRED"
    else:
        raise AssertionError("expected DomainError")


def test_task_can_move_to_done_from_progress():
    validate_task_transition("IN_PROGRESS", "DONE")


def test_submission_review_transition_is_explicit():
    validate_submission_status("WAITING_REVIEW", "REVIEWED")
    try:
        validate_submission_status("DRAFT", "REVIEWED")
    except DomainError as exc:
        assert exc.code == "INVALID_STATE_TRANSITION"
    else:
        raise AssertionError("expected DomainError")

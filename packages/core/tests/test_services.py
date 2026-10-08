from datetime import date

import pytest

from studyflow.domain import DomainError


def test_seed_and_dashboard_expose_primary_task(app_service):
    result = app_service.seed_demo(date(2026, 9, 28))
    assert result["created"] is True
    dashboard = app_service.dashboard(date(2026, 9, 28))
    assert dashboard["primary_task"].title.startswith("完成 StudyFlow")
    assert len(dashboard["courses"]) == 1


def test_submission_and_review_keep_original_answer(app_service):
    seeded = app_service.seed_demo(date(2026, 9, 28))
    submission = app_service.submit_answer(seeded["exercise_id"], "这是我的第一次解释。", seeded["task_id"], "submission-1")
    assert submission.status == "WAITING_REVIEW"
    review = app_service.write_review(submission.id, "核心方向正确，但需要更准确地区分引用值与指针。", "保留原答案，补充值传递解释。", 1, True, "review-1")
    assert review.needs_revision is True
    stored = app_service.get_submission(submission.id)
    assert stored.answer_text == "这是我的第一次解释。"
    assert stored.status == "NEEDS_REVISION"


def test_idempotent_submission_does_not_duplicate(app_service):
    seeded = app_service.seed_demo()
    first = app_service.submit_answer(seeded["exercise_id"], "同一答案", idempotency_key="same")
    second = app_service.submit_answer(seeded["exercise_id"], "同一答案", idempotency_key="same")
    assert first.id == second.id
    assert second.answer_text == "同一答案"


def test_document_missing_is_explicit(app_service):
    document = app_service.check_document("content/does-not-exist.md")
    assert document.status == "MISSING"


def test_plan_lines_tasks_and_courses_are_filtered_generically(app_service):
    from datetime import date

    exam = app_service.create_plan_line("Software Designer", priority=1)
    english = app_service.create_plan_line("English CET-4", priority=2)
    exam_task = app_service.create_task("Review database keys", date(2026, 9, 28), "EXAM", plan_line_id=exam.id)
    english_task = app_service.create_task("Practice present tense", date(2026, 9, 28), "PRACTICE", plan_line_id=english.id)
    assert [task.title for task in app_service.list_tasks(date(2026, 9, 28), plan_line_id=exam.id)] == [exam_task.title]
    assert [task.title for task in app_service.list_tasks(date(2026, 9, 28), task_kind="PRACTICE")] == [english_task.title]
    assert {line.name for line in app_service.list_plan_lines()} == {"Software Designer", "English CET-4"}


def test_import_markdown_course_is_idempotent_and_does_not_change_source(app_service, tmp_path):
    from pathlib import Path

    plan = app_service.create_plan_line("Software Designer")
    source = tmp_path / "exam" / "database.md"
    source.parent.mkdir()
    content = """---
course: Database Fundamentals
lesson: Relational Model and Keys
plan_line: Software Designer
subject: Database
content_type: EXAM_PREP
difficulty: FOUNDATION
source_type: CODEX
summary: Review keys and constraints.
document_type: LESSON
exercises:
  - title: Candidate key
    type: EXAM_QUESTION
    prompt: Explain candidate keys.
    requirements: Mention uniqueness and minimality.
---
# Relational Model

A relation is a set of tuples.
"""
    source.write_text(content, encoding="utf-8")
    first = app_service.import_course_markdown("exam/database.md")
    second = app_service.import_course_markdown("exam/database.md")
    assert first["created"] is True
    assert second["created"] is False
    assert first["lesson_id"] == second["lesson_id"]
    assert source.read_text(encoding="utf-8") == content
    course = app_service.get_course(first["course_id"])
    assert course.plan_line_id == plan.id
    assert course.subject == "Database"
    assert course.lessons[0].exercises[0].exercise_type == "EXAM_QUESTION"


def test_markdown_import_rejects_unknown_plan_line(app_service, tmp_path):
    from studyflow.domain import DomainError

    (tmp_path / "lesson.md").write_text("---\ncourse: C\nlesson: L\nplan_line: Missing\n---\n# Text", encoding="utf-8")
    with pytest.raises(DomainError) as exc:
        app_service.import_course_markdown("lesson.md")
    assert exc.value.code == "PLAN_LINE_NOT_FOUND"


def test_course_is_ordered_and_dashboard_exposes_knowledge_progress(app_service):
    seeded = app_service.seed_demo(date(2026, 9, 28))
    plan = app_service.get_plan_line(seeded["plan_line_id"])
    assert plan is not None
    dashboard = app_service.dashboard(date(2026, 9, 28), plan_line_id=plan.id)
    assert dashboard["course_position"] == 1
    assert dashboard["course_total"] == 1
    assert dashboard["courses"][0].knowledge_total == 3
    assert dashboard["courses"][0].schedule_item is not None


def test_submission_lifecycle_keeps_parent_chain(app_service):
    seeded = app_service.seed_demo()
    first = app_service.submit_answer(seeded["exercise_id"], "第一次答案")
    app_service.write_review(first.id, "需要重新组织论证", issue_count=1, decision="REVISION_REQUIRED")
    revision = app_service.revise_submission(first.id, "这是修正版答案")
    assert revision.parent_submission_id == first.id
    assert revision.attempt_number == 2
    app_service.write_review(revision.id, "需要脱离原答案复述", decision="RETEST_REQUIRED")
    from studyflow.modules.reviews.retests import publish
    publish(app_service.reviews,revision.id,"独立复测题","解释一个新场景","独立应用能力","publish-"+revision.id)
    retest = app_service.retest_submission(revision.id, "这是复测答案")
    assert retest.parent_submission_id == revision.id
    assert retest.attempt_kind == "RETEST"
    app_service.write_review(retest.id, "已掌握", decision="PASSED")
    assert app_service.get_submission(retest.id).status == "PASSED"


def test_agent_queue_separates_three_actions(app_service):
    seeded = app_service.seed_demo()
    submission = app_service.submit_answer(seeded["exercise_id"], "答案")
    queue = app_service.agent_queue()
    assert queue["waiting_review"][0]["id"] == submission.id
    app_service.write_review(submission.id, "请修正", decision="REVISION_REQUIRED")
    queue = app_service.agent_queue()
    assert queue["needs_revision"][0]["id"] == submission.id


def test_new_plan_and_snapshot_events_use_agent_cli_source(app_service):
    from sqlalchemy import select

    from studyflow.models import EventLog

    plan = app_service.create_plan_line("Agent-neutral source")
    snapshot = app_service.generate_snapshot()

    with app_service.session() as db:
        plan_event = db.scalar(select(EventLog).where(EventLog.object_type == "plan_line", EventLog.object_id == plan.id))
        snapshot_event = db.scalar(select(EventLog).where(EventLog.object_type == "snapshot", EventLog.object_id == snapshot.id))

    assert plan_event is not None
    assert plan_event.source == "AGENT_CLI"
    assert snapshot_event is not None
    assert snapshot_event.source == "AGENT_CLI"


def test_passed_submission_can_still_start_revision_and_retest(app_service):
    seeded = app_service.seed_demo()
    first = app_service.submit_answer(seeded["exercise_id"], "答案")
    app_service.write_review(first.id, "方向正确", decision="PASSED")
    revision = app_service.revise_submission(first.id, "主动补充后的修正版")
    assert revision.parent_submission_id == first.id
    app_service.write_review(revision.id, "复测前再独立组织", decision="RETEST_REQUIRED")
    from studyflow.modules.reviews.retests import publish
    publish(app_service.reviews,revision.id,"独立复测题","解释一个新场景","独立应用能力","publish-"+revision.id)
    retest = app_service.retest_submission(revision.id, "独立复测答案")
    assert retest.parent_submission_id == revision.id


def test_agent_queue_returns_leaf_context_and_drops_parent_after_followup(app_service):
    seeded = app_service.seed_demo()
    first = app_service.submit_answer(seeded["exercise_id"], "第一次答案")
    app_service.write_review(first.id, "需要修正", decision="REVISION_REQUIRED")
    revision = app_service.revise_submission(first.id, "修正版答案")
    queue = app_service.agent_queue()
    assert first.id not in [item["id"] for item in queue["items"]]
    item = next(item for item in queue["items"] if item["id"] == revision.id)
    assert item["lesson_id"]
    assert item["lesson_title"]
    assert item["markdown_path"]
    assert item["plan_line_id"] == seeded["plan_line_id"]
    assert item["parent_submission_id"] == first.id
    assert item["answer_text"] == "修正版答案"
    assert item["context"]["submission_id"] == revision.id

def test_review_and_followup_idempotency_conflicts_are_rejected(app_service):
    from studyflow.domain import DomainError
    seeded = app_service.seed_demo()
    first = app_service.submit_answer(seeded["exercise_id"], "第一次答案")
    review = app_service.write_review(first.id, "需要修正", decision="REVISION_REQUIRED", idempotency_key="review-stable")
    assert app_service.write_review(first.id, "需要修正", decision="REVISION_REQUIRED", idempotency_key="review-stable").id == review.id
    with pytest.raises(DomainError) as review_conflict:
        app_service.write_review(first.id, "另一份批改", decision="REVISION_REQUIRED", idempotency_key="review-stable")
    assert review_conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    revision = app_service.revise_submission(first.id, "修正版答案", idempotency_key="followup-stable")
    assert app_service.revise_submission(first.id, "修正版答案", idempotency_key="followup-stable").id == revision.id
    with pytest.raises(DomainError) as followup_conflict:
        app_service.revise_submission(first.id, "修改后的另一份答案", idempotency_key="followup-stable")
    assert followup_conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    with pytest.raises(DomainError) as review_state:
        app_service.write_review(first.id, "重复批改", decision="PASSED")
    assert review_state.value.code == "INVALID_REVIEW_SOURCE"

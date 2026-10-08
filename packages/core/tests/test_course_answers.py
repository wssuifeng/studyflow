from __future__ import annotations

import pytest
from sqlalchemy import select, func
from studyflow.domain import DomainError
from studyflow.models import Course, Exercise, Lesson, Submission
from studyflow.services import new_id
from studyflow.engine import StudyFlowEngine


@pytest.fixture
def multi_course(app_service):
    seeded = app_service.seed_demo()
    identifiers = []
    with app_service.session() as db:
        course = Course(id=new_id(), plan_line_id=seeded["plan_line_id"], title="整课测试", summary="")
        db.add(course)
        for position in (1, 2):
            lesson = Lesson(id=new_id(), course_id=course.id, title=f"知识点{position}", position=position,
                            markdown_path="content/second.md", summary="")
            db.add(lesson)
            exercise = Exercise(id=new_id(), lesson_id=lesson.id, title=f"第{position}题", prompt="解释状态", position=1)
            db.add(exercise)
            identifiers.append(exercise.id)
        db.flush()
        course_id = course.id
    return course_id, identifiers


def entries(ids):
    return [{"exercise_id": identifier, "answer_text": f"第{i + 1}题：中文答案 ✅"} for i, identifier in enumerate(ids)]


def count(app_service):
    with app_service.session() as db:
        return db.scalar(select(func.count(Submission.id)))


def test_whole_course_draft_submit_and_replay(app_service, multi_course):
    course_id, ids = multi_course
    payload = entries(ids)
    saved = app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "course-save")
    assert len(saved["submissions"]) == 2
    assert all(row["status"] == "DRAFT" for row in saved["submissions"])
    assert app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "course-save") == saved
    submitted_payload = [{**item, "submission_id": row["id"], "expected_version": row["version"]}
                         for item, row in zip(payload, saved["submissions"])]
    submitted = app_service.write_course_answers(course_id, submitted_payload, "SUBMIT", "course-submit")
    assert all(row["status"] == "WAITING_REVIEW" for row in submitted["submissions"])
    assert app_service.write_course_answers(course_id, submitted_payload, "SUBMIT", "course-submit") == submitted
    # Old receipts return the original snapshot, not the subsequently changed rows.
    assert app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "course-save") == saved
    assert count(app_service) == 2
    sheet = app_service.course_answer_sheet(course_id)
    assert [item["submission"]["answer_text"] for item in sheet["answers"]] == [p["answer_text"] for p in payload]
    assert len(app_service.agent_queue()["waiting_review"]) == 2


@pytest.mark.parametrize("fault", ["blank", "foreign", "duplicate", "omitted"])
def test_course_submit_is_all_or_nothing(app_service, multi_course, fault):
    course_id, ids = multi_course
    payload = entries(ids)
    if fault == "blank": payload[1]["answer_text"] = "  "
    if fault == "foreign": payload[1]["exercise_id"] = "not-this-course"
    if fault == "duplicate": payload[1]["exercise_id"] = ids[0]
    if fault == "omitted": payload.pop()
    with pytest.raises(DomainError):
        app_service.write_course_answers(course_id, payload, "SUBMIT", "bad-course-submit")
    assert count(app_service) == 0


def test_batch_conflict_rolls_back_every_answer(app_service, multi_course):
    course_id, ids = multi_course
    payload = entries(ids)
    saved = app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "first")
    update = [{**item, "submission_id": row["id"], "expected_version": row["version"], "answer_text": "修改答案"}
              for item, row in zip(payload, saved["submissions"])]
    app_service.save_submission_draft(ids[1], "另一个客户端的草稿", saved["submissions"][1]["id"], expected_version=1)
    with pytest.raises(DomainError, match="版本"):
        app_service.write_course_answers(course_id, update, "DRAFT_SAVE", "stale-batch")
    assert app_service.submission_detail(saved["submissions"][0]["id"])["answer_text"] == payload[0]["answer_text"]
    assert app_service.submission_detail(saved["submissions"][0]["id"])["version"] == 1


def test_batch_same_key_changed_payload_is_conflict(app_service, multi_course):
    course_id, ids = multi_course
    payload = entries(ids)
    app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "stable-key")
    payload[0]["answer_text"] = "另一个答案"
    with pytest.raises(DomainError) as failure:
        app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "stable-key")
    assert failure.value.code == "IDEMPOTENCY_KEY_CONFLICT"


def test_batch_followups_keep_originals_and_join_agent_queue(app_service, multi_course):
    course_id, ids = multi_course
    original = app_service.write_course_answers(course_id, entries(ids), "SUBMIT", "original")
    first, second = original["submissions"]
    app_service.write_review(first["id"], "需要修正", "原句与解释", decision="REVISION_REQUIRED")
    app_service.write_review(second["id"], "需要复测", "再次解释", decision="RETEST_REQUIRED")
    payload = [{**item, "parent_submission_id": row["id"]} for item, row in zip(entries(ids), original["submissions"])]
    from studyflow.modules.reviews.retests import publish
    retest=publish(app_service.reviews,second["id"],"独立复测","解释新的场景","校验状态理解","batch-retest")
    payload[1]["retest_task_id"]=retest["id"]
    draft = app_service.write_course_answers(course_id, payload, "DRAFT_SAVE", "followup-draft")
    assert [r["attempt_kind"] for r in draft["submissions"]] == ["REVISION", "RETEST"]
    submit_payload = [{**item, "submission_id": row["id"], "expected_version": row["version"]}
                      for item, row in zip(payload, draft["submissions"])]
    result = app_service.write_course_answers(course_id, submit_payload, "SUBMIT", "followup-submit")
    assert [r["parent_submission_id"] for r in result["submissions"]] == [first["id"], second["id"]]
    assert app_service.submission_detail(first["id"])["status"] == "NEEDS_REVISION"
    assert app_service.submission_detail(second["id"])["status"] == "RETEST_REQUIRED"
    assert len(app_service.agent_queue()["waiting_review"]) == 2


def test_batch_cannot_bypass_waiting_review(app_service, multi_course):
    course_id, ids = multi_course
    app_service.write_course_answers(course_id, entries(ids), "SUBMIT", "initial")
    with pytest.raises(DomainError):
        app_service.write_course_answers(course_id, entries(ids), "SUBMIT", "resubmit")
    assert count(app_service) == 2


def test_course_answer_protocol_rejects_invalid_shape(app_service, multi_course):
    course_id, ids = multi_course
    engine = StudyFlowEngine(service=app_service)
    try:
        response = engine.handle({"id": 1, "method": "course.answers.submit", "params": {
            "course_id": course_id, "answers": "not-an-array", "idempotency_key": "invalid-shape"}})
        assert response["error"]["code"] == "INVALID_ARGUMENT"
        valid = engine.handle({"id": 2, "method": "course.answers.draft.save", "params": {
            "course_id": course_id, "answers": entries(ids), "idempotency_key": "protocol-save"}})
        assert valid["ok"] is True
        assert len(valid["data"]["submissions"]) == 2
    finally:
        engine.close()



def test_cli_exposes_whole_course_answers(app_service, multi_course, monkeypatch, tmp_path):
    import json
    from typer.testing import CliRunner
    import studyflow.cli as cli
    course_id, ids = multi_course
    monkeypatch.setattr(cli, "service", lambda: app_service)
    file = tmp_path / "answers.json"
    file.write_text(json.dumps({"answers": entries(ids)}, ensure_ascii=False), encoding="utf-8")
    runner = CliRunner()
    saved = runner.invoke(cli.app, ["course", "answers", "save", "--id", course_id, "--file", str(file),
        "--idempotency-key", "cli-course-save", "--format", "json"])
    assert saved.exit_code == 0, saved.output
    assert len(json.loads(saved.stdout)["submissions"]) == 2
    read = runner.invoke(cli.app, ["course", "answers", "get", "--id", course_id, "--format", "json"])
    assert read.exit_code == 0, read.output
    assert len(json.loads(read.stdout)["answers"]) == 2


def test_followup_sheet_reads_draft_without_hiding_original(app_service, multi_course):
    course_id, ids = multi_course
    result = app_service.write_course_answers(course_id, entries(ids), "SUBMIT", "original-for-sheet")
    first = result["submissions"][0]
    app_service.write_review(first["id"], "修正", "原答案需要说明边界", decision="REVISION_REQUIRED")
    draft = app_service.write_course_answers(course_id, [{"exercise_id": ids[0], "answer_text": "待完成的修正", "parent_submission_id": first["id"]}], "DRAFT_SAVE", "revision-sheet-draft")
    sheet = app_service.course_answer_sheet(course_id)
    item = next(item for item in sheet["answers"] if item["exercise_id"] == ids[0])
    assert item["draft"]["id"] == draft["submissions"][0]["id"]
    assert item["submission"]["id"] == first["id"]
    assert item["action"] == "REVISION"
    assert item["submission"]["reviews"][0]["detail_markdown"] == "原答案需要说明边界"

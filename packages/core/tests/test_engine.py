from __future__ import annotations

import io
import json

import pytest

from studyflow.engine import StudyFlowEngine, run_stdio


def test_engine_system_discovery_and_today(app_service, monkeypatch):
    import studyflow.engine as engine_module

    seeded = app_service.seed_demo()
    settings = app_service.settings
    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    engine = StudyFlowEngine(settings)
    try:
        version = engine.handle({"id": 1, "method": "system.version", "params": {}})
        assert version["ok"] is True
        assert version["data"]["protocol_version"] == "1.2"

        capabilities = engine.handle({"id": 2, "method": "system.capabilities", "params": {}})
        assert "review_write" in [item["name"] for item in capabilities["data"]["capabilities"]]

        today = engine.handle({"id": 3, "method": "study.today", "params": {}})
        assert today["ok"] is True
        assert today["data"]["current_course"]["id"] == seeded["course_id"]
    finally:
        engine.close()


def test_engine_queue_and_unknown_method(app_service, monkeypatch):
    import studyflow.engine as engine_module

    seeded = app_service.seed_demo()
    app_service.submit_answer(seeded["exercise_id"], "答案")
    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    engine = StudyFlowEngine(app_service.settings)
    try:
        queue = engine.handle({"id": "q", "method": "assignment.queue", "params": {}})
        assert queue["ok"] is True
        assert queue["data"]["waiting_review"]
        summary = engine.handle({"id": "summary", "method": "assignment.summary", "params": {"limit": 50}})
        assert summary["ok"] is True
        assert summary["data"]["items"]
        unknown = engine.handle({"id": "bad", "method": "not.exists", "params": {}})
        assert unknown["ok"] is False
        assert unknown["error"]["code"] == "METHOD_NOT_FOUND"
    finally:
        engine.close()


def test_engine_stdio_keeps_one_response_per_request(app_service, monkeypatch):
    import studyflow.engine as engine_module

    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    engine = StudyFlowEngine(app_service.settings)
    try:
        source = io.StringIO(json.dumps({"id": 1, "method": "system.version", "params": {}}) + "\n" + json.dumps({"id": 2, "method": "system.capabilities", "params": {}}) + "\n")
        target = io.StringIO()
        run_stdio(engine, source, target)
        rows = [json.loads(line) for line in target.getvalue().splitlines()]
        assert [row["id"] for row in rows] == [1, 2]
        assert all(row["ok"] for row in rows)
    finally:
        engine.close()


def test_engine_import_rejects_path_outside_workspace(app_service, monkeypatch, tmp_path):
    import studyflow.engine as engine_module

    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    engine = StudyFlowEngine(app_service.settings)
    try:
        result = engine.handle({"id": 4, "method": "course.import", "params": {"path": str(tmp_path / "outside.md")}})
        assert result["ok"] is False
        assert "工作区" in result["error"]["message"] or result["error"]["code"] == "INTERNAL_ERROR"
    finally:
        engine.close()

def test_engine_rejects_non_object_request_without_leaking_credentials(app_service, monkeypatch):
    import studyflow.engine as engine_module

    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    engine = StudyFlowEngine(app_service.settings)
    try:
        invalid = engine.handle(["not", "an", "object"])
        assert invalid["ok"] is False
        assert invalid["error"]["code"] == "INVALID_REQUEST"
        assert "请求必须是 JSON 对象" in invalid["error"]["message"]

        from studyflow.engine_protocol import error_payload
        payload = error_payload(RuntimeError("mysql+pymysql://user:secret@localhost/db?password=secret"))
        assert "secret" not in payload["message"]
        assert payload["code"] == "INTERNAL_ERROR"
    finally:
        engine.close()



@pytest.fixture
def engine_client(app_service, monkeypatch):
    import studyflow.engine as engine_module

    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    client = StudyFlowEngine(app_service.settings)
    try:
        yield client
    finally:
        client.close()


def call(engine_client, method, params, request_id="s1"):
    return engine_client.handle({"id": request_id, "method": method, "params": params})


def test_engine_s1_capabilities_are_discoverable(engine_client):
    result = call(engine_client, "system.capabilities", {})
    methods = {item["method"] for item in result["data"]["capabilities"]}
    assert {
        "plan.detail", "course.detail", "document.read", "submission.get",
        "submission.draft.save", "submission.submit", "learning.progress.save",
    }.issubset(methods)


def test_plan_and_course_details_return_ordered_multi_lesson_contract(app_service, engine_client):
    seeded = app_service.seed_demo()
    plan = call(engine_client, "plan.detail", {"plan_line_id": seeded["plan_line_id"]})
    course = call(engine_client, "course.detail", {"course_id": seeded["course_id"]})
    assert plan["ok"] is True
    assert plan["data"]["courses"][0]["sequence"] == 1
    assert course["ok"] is True
    assert len(course["data"]["lessons"]) == 3
    assert [item["position"] for item in course["data"]["lessons"]] == [1, 2, 3]
    assert course["data"]["lessons"][0]["exercises"][0]["id"] == seeded["exercise_id"]


def test_engine_detail_not_found_and_invalid_arguments_are_stable(engine_client):
    missing_plan = call(engine_client, "plan.detail", {"plan_line_id": "missing"})
    missing_course = call(engine_client, "course.detail", {"course_id": "missing"})
    missing_submission = call(engine_client, "submission.get", {"submission_id": "missing"})
    invalid_progress = call(engine_client, "learning.progress.save", {"course_id": "x", "lesson_id": "y", "progress_percent": 120})
    assert [item["error"]["code"] for item in (missing_plan, missing_course, missing_submission)] == ["OBJECT_NOT_FOUND"] * 3
    assert invalid_progress["error"]["code"] == "INVALID_ARGUMENT"
    assert all(item["error"].get("next_action") for item in (missing_plan, missing_course, missing_submission, invalid_progress))


def test_document_read_is_markdown_only_workspace_relative_and_safe(app_service, engine_client, tmp_path):
    doc = app_service.settings.workspace_root / "content" / "lessons" / "safe.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Safe\n\n<script>alert(1)</script>Visible", encoding="utf-8")
    result = call(engine_client, "document.read", {"path": "content/lessons/safe.md"})
    assert result["ok"] is True
    assert result["data"]["status"] == "PRESENT"
    assert "<script" not in result["data"]["html"]
    assert result["data"]["content_hash"]
    traversal = call(engine_client, "document.read", {"path": "../outside.md"})
    absolute = call(engine_client, "document.read", {"path": str(doc)})
    missing = call(engine_client, "document.read", {"path": "content/missing.md"})
    unsupported = call(engine_client, "document.read", {"path": "content/file.txt"})
    assert traversal["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
    assert absolute["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
    assert missing["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert unsupported["error"]["code"] == "UNSUPPORTED_DOCUMENT_TYPE"


def test_draft_submit_get_and_review_lifecycle_are_idempotent_and_immutable(app_service, engine_client):
    seeded = app_service.seed_demo()
    saved = call(engine_client, "submission.draft.save", {
        "exercise_id": seeded["exercise_id"], "answer_text": "草稿一", "idempotency_key": "draft-1",
    })["data"]
    repeated = call(engine_client, "submission.draft.save", {
        "exercise_id": seeded["exercise_id"], "answer_text": "草稿一", "idempotency_key": "draft-1",
    })["data"]
    assert repeated["id"] == saved["id"]
    assert app_service.agent_queue()["items"] == []

    updated = call(engine_client, "submission.draft.save", {
        "exercise_id": seeded["exercise_id"], "submission_id": saved["id"],
        "answer_text": "最终答案", "idempotency_key": "draft-2",
    })["data"]
    assert updated["version"] == 2
    submitted = call(engine_client, "submission.submit", {
        "submission_id": saved["id"], "idempotency_key": "submit-1",
    })["data"]
    replay = call(engine_client, "submission.submit", {
        "submission_id": saved["id"], "idempotency_key": "submit-1",
    })["data"]
    assert submitted["status"] == "WAITING_REVIEW"
    assert replay["id"] == submitted["id"]
    assert app_service.agent_queue()["waiting_review"][0]["id"] == saved["id"]

    app_service.write_review(saved["id"], "请修正", decision="REVISION_REQUIRED")
    detail = call(engine_client, "submission.get", {"submission_id": saved["id"]})["data"]
    assert detail["answer_text"] == "最终答案"
    assert detail["reviews"][0]["decision"] == "REVISION_REQUIRED"
    assert detail["children"] == []
    invalid_resubmit = call(engine_client, "submission.submit", {"submission_id": saved["id"]})
    assert invalid_resubmit["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_engine_draft_does_not_regress_passed_course_progress(app_service, engine_client):
    seeded = app_service.seed_demo()
    passed = app_service.submit_answer(seeded["exercise_id"], "已通过答案")
    app_service.write_review(passed.id, "通过", decision="PASSED")
    course = app_service.get_course(seeded["course_id"])
    for lesson in course.lessons:
        for exercise in lesson.exercises:
            submission = app_service.submit_answer(exercise.id, "已通过答案")
            app_service.write_review(submission.id, "通过", decision="PASSED")
    before = call(engine_client, "course.detail", {"course_id": seeded["course_id"]})["data"]["course"]["progress_percent"]
    call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "answer_text": "新草稿"})
    after = call(engine_client, "course.detail", {"course_id": seeded["course_id"]})["data"]["course"]["progress_percent"]
    assert before == after == 100


def test_learning_progress_persists_and_is_readable_from_another_engine(app_service, engine_client):
    seeded = app_service.seed_demo()
    detail = call(engine_client, "course.detail", {"course_id": seeded["course_id"]})["data"]
    lesson = detail["lessons"][0]
    saved = call(engine_client, "learning.progress.save", {
        "course_id": seeded["course_id"], "lesson_id": lesson["id"],
        "progress_percent": 65, "last_position": "heading:references",
    })
    assert saved["data"]["status"] == "IN_PROGRESS"

    second = StudyFlowEngine(app_service.settings)
    try:
        reloaded = second.handle({"id": "reload", "method": "course.detail", "params": {"course_id": seeded["course_id"]}})
        progress = reloaded["data"]["lessons"][0]["progress"]
        assert progress == {"progress_percent": 65, "status": "IN_PROGRESS", "last_position": "heading:references"}
        assert progress["progress_percent"] != reloaded["data"]["course"]["progress_percent"]
    finally:
        second.close()


def test_learning_progress_rejects_cross_course_lesson(app_service, engine_client):
    seeded = app_service.seed_demo()
    other = app_service.create_plan_line("Other plan")
    from studyflow.models import Course, Lesson
    from studyflow.services import new_id
    with app_service.session() as db:
        course = Course(id=new_id(), plan_line=other, title="Other course")
        lesson = Lesson(id=new_id(), course=course, title="Other lesson", position=1, markdown_path="content/other.md")
        db.add(course)
        db.flush()
        other_lesson_id = lesson.id
    result = call(engine_client, "learning.progress.save", {
        "course_id": seeded["course_id"], "lesson_id": other_lesson_id, "progress_percent": 10,
    })
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_old_draft_keys_replay_after_new_saves_and_submission(app_service, engine_client):
    seeded = app_service.seed_demo()
    first = call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "answer_text": "first", "idempotency_key": "old-draft"})["data"]
    second = call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "submission_id": first["id"], "answer_text": "second", "idempotency_key": "new-draft", "expected_version": 1})["data"]
    replay = call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "answer_text": "first", "idempotency_key": "old-draft"})["data"]
    assert replay["id"] == first["id"]
    assert replay["version"] == first["version"]
    assert app_service.get_submission(first["id"]).answer_text == "second"
    call(engine_client, "submission.submit", {"submission_id": first["id"], "idempotency_key": "submit-key"})
    replay = call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "answer_text": "first", "idempotency_key": "old-draft"})
    assert replay["data"]["status"] == "DRAFT"
    assert len(app_service.agent_queue()["waiting_review"]) == 1


def test_conflicting_draft_version_and_missing_task_do_not_mutate(app_service, engine_client):
    seeded = app_service.seed_demo()
    draft = call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "answer_text": "original"})["data"]
    conflict = call(engine_client, "submission.draft.save", {"exercise_id": seeded["exercise_id"], "submission_id": draft["id"], "answer_text": "stale", "expected_version": 0})
    assert conflict["error"]["code"] == "VERSION_CONFLICT"
    missing_task = call(engine_client, "submission.submit", {"exercise_id": seeded["exercise_id"], "answer_text": "answer", "task_id": "missing"})
    assert missing_task["error"]["code"] == "OBJECT_NOT_FOUND"
    assert app_service.get_submission(draft["id"]).answer_text == "original"
    assert app_service.agent_queue()["items"] == []


@pytest.mark.parametrize("method, service_name, params", [
    ("plan.detail", "plan_detail", {"plan_line_id": "p"}),
    ("course.detail", "course_detail", {"course_id": "c"}),
    ("document.read", "read_document", {"path": "lesson.md"}),
    ("submission.get", "submission_detail", {"submission_id": "s"}),
    ("submission.draft.save", "save_submission_draft", {"exercise_id": "e"}),
    ("submission.submit", "submit_submission", {"exercise_id": "e", "answer_text": "a"}),
    ("learning.progress.save", "save_learning_progress", {"course_id": "c", "lesson_id": "l", "progress_percent": 1}),
])
def test_protocol_database_errors_are_structured_and_do_not_leak(engine_client, monkeypatch, method, service_name, params):
    from sqlalchemy.exc import OperationalError
    def fail(*args, **kwargs):
        raise OperationalError("SELECT secret FROM private_path", {}, RuntimeError("C:/private/database.db password=private"))
    monkeypatch.setattr(engine_client.service, service_name, fail)
    response = call(engine_client, method, params)
    assert response["ok"] is False
    assert response["error"]["code"] == "DATABASE_ERROR"
    assert response["error"]["next_action"]
    assert "private" not in json.dumps(response)


def test_document_symlink_escape_is_rejected(app_service, engine_client, tmp_path):
    target = tmp_path.parent / (tmp_path.name + "-outside.md")
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this host")
    response = call(engine_client, "document.read", {"path": "link.md"})
    assert response["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"


def test_engine_s3_queue_context_and_followup_lifecycle(app_service, engine_client):
    seeded = app_service.seed_demo()
    first = call(engine_client, "submission.submit", {"exercise_id": seeded["exercise_id"], "answer_text": "原始答案", "idempotency_key": "s3-engine-first"})["data"]
    queue = call(engine_client, "assignment.queue", {})["data"]
    item = next(item for item in queue["items"] if item["id"] == first["id"])
    assert item["lesson_id"] == app_service.get_course(seeded["course_id"]).lessons[0].id
    assert item["plan_line_id"] == seeded["plan_line_id"]
    assert item["answer_text"] == "原始答案"
    assert item["context"]["submission_id"] == first["id"]
    reviewed = call(engine_client, "review.write", {"submission_id": first["id"], "summary": "需要修正", "decision": "REVISION_REQUIRED", "idempotency_key": "s3-engine-review"})
    assert reviewed["ok"] is True
    revision = call(engine_client, "submission.revise", {"parent_submission_id": first["id"], "answer_text": "修正版答案", "idempotency_key": "s3-engine-revision"})
    assert revision["data"]["source"] == "USER_WEB"
    queue_after = call(engine_client, "assignment.queue", {})["data"]
    assert first["id"] not in [item["id"] for item in queue_after["items"]]
    assert revision["data"]["submission_id"] in [item["id"] for item in queue_after["items"]]
    blocked = call(engine_client, "submission.retest", {"parent_submission_id": revision["data"]["submission_id"], "answer_text": "越级复测"})
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "INVALID_ATTEMPT_SOURCE"


def test_unexpected_engine_error_has_safe_durable_diagnostic(engine_client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("mysql+pymysql://user:secret@localhost/db answer-private sk-hidden")
    monkeypatch.setattr(engine_client.service, "course_detail", broken)
    result = call(engine_client, "course.detail", {"course_id": "missing"})
    assert result["ok"] is False
    diagnostic = result["error"]
    entries = [json.loads(line) for line in engine_client.settings.log_root.joinpath("engine-errors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert entries[-1]["diagnostic_id"] == diagnostic["diagnostic_id"]
    assert entries[-1]["exception_type"] == "RuntimeError"
    combined = json.dumps(entries) + json.dumps(result)
    assert "secret" not in combined and "answer-private" not in combined and "sk-hidden" not in combined
    assert entries[-1]["frames"]


def test_main_uses_utf8_for_all_protocol_streams(app_service, engine_client, monkeypatch):
    import studyflow.engine as engine_module
    import sys
    seeded = app_service.seed_demo()
    answer = "70度正常，71度告警。\n引用与状态 ✅"
    requests = [{"id": "unicode", "method": "submission.draft.save", "params": {
        "exercise_id": seeded["exercise_id"], "answer_text": answer,
        "idempotency_key": "utf8-main-test",
    }}]
    source = io.TextIOWrapper(io.BytesIO((json.dumps(requests[0], ensure_ascii=False) + "\n").encode("utf-8")),
                              encoding="gbk", errors="surrogateescape")
    output_buffer = io.BytesIO()
    target = io.TextIOWrapper(output_buffer, encoding="gbk")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    monkeypatch.setattr(sys, "stdin", source)
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(engine_module, "StudyFlowEngine", lambda: engine_client)
    engine_module.main()
    target.flush()
    result = json.loads(output_buffer.getvalue().decode("utf-8"))
    assert result["ok"] is True, result
    assert app_service.submission_detail(result["data"]["id"])["answer_text"] == answer
    assert source.encoding == target.encoding == stderr.encoding == "utf-8"

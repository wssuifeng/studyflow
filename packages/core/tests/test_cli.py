from typer.testing import CliRunner

from studyflow.cli import app


def test_cli_help_is_available():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "StudyFlow" in result.stdout


def test_plan_create_and_list_json(monkeypatch, app_service):
    import json
    import studyflow.cli as cli

    monkeypatch.setattr(cli, "service", lambda: app_service)
    runner = CliRunner()
    created = runner.invoke(app, ["plan", "create", "--name", "English CET-4", "--format", "json"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)["name"] == "English CET-4"
    listed = runner.invoke(app, ["plan", "list", "--format", "json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["plans"][0]["name"] == "English CET-4"


def test_course_import_command(monkeypatch, app_service, tmp_path):
    import studyflow.cli as cli

    plan = app_service.create_plan_line("Java Employment")
    monkeypatch.setattr(cli, "service", lambda: app_service)
    source = tmp_path / "lesson.md"
    source.write_text("---\ncourse: Java Basics\nlesson: References\nplan_line: Java Employment\n---\n# References", encoding="utf-8")
    result = CliRunner().invoke(app, ["course", "import", "--file", str(source), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert plan.id
    assert "Java Basics" in result.stdout


def test_task_top_level_aliases(monkeypatch, app_service):
    import json
    import studyflow.cli as cli

    plan = app_service.create_plan_line("Task Alias Plan")
    monkeypatch.setattr(cli, "service", lambda: app_service)
    runner = CliRunner()
    created = runner.invoke(app, ["task", "create", "--title", "Read lesson", "--date", "2026-09-28", "--plan-line", plan.id, "--kind", "READING", "--format", "json"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)["kind"] == "READING"
    listed = runner.invoke(app, ["task", "list", "--date", "2026-09-28", "--format", "json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["tasks"][0]["title"] == "Read lesson"


def test_agent_queue_and_explicit_review_decision(monkeypatch, app_service):
    import json
    import studyflow.cli as cli

    seeded = app_service.seed_demo()
    submission = app_service.submit_answer(seeded["exercise_id"], "答案")
    monkeypatch.setattr(cli, "service", lambda: app_service)
    runner = CliRunner()
    queued = runner.invoke(app, ["assignment", "queue", "--format", "json"])
    assert queued.exit_code == 0, queued.output
    assert json.loads(queued.stdout)["waiting_review"][0]["id"] == submission.id
    reviewed = runner.invoke(app, ["review", "write", "--submission", submission.id, "--summary", "已掌握", "--decision", "PASSED", "--format", "json"])
    assert reviewed.exit_code == 0, reviewed.output
    assert json.loads(reviewed.stdout)["decision"] == "PASSED"


def test_agent_queue_json_preserves_chinese_text(monkeypatch, app_service):
    import json
    import studyflow.cli as cli

    seeded = app_service.seed_demo()
    app_service.submit_answer(seeded["exercise_id"], "测试答案")
    monkeypatch.setattr(cli, "service", lambda: app_service)
    result = CliRunner().invoke(app, ["assignment", "queue", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "用自己的话解释引用值副本与对象字段修改。" in payload["waiting_review"][0]["exercise_title"]
    assert "\\u" not in result.stdout


def test_cli_capability_discovery_contract(monkeypatch, tmp_path):
    import json
    import studyflow.cli as cli
    from studyflow.config import Settings

    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{(tmp_path / 'discovery.db').as_posix()}")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls, base_dir=None: settings))
    runner = CliRunner()

    version = runner.invoke(app, ["version", "--format", "json"])
    assert version.exit_code == 0, version.output
    version_payload = json.loads(version.stdout)
    assert version_payload["protocol_version"] == "1.2"
    assert version_payload["workspace"]["exists"] is True
    assert version_payload["database"]["status"] == "not_checked"

    capabilities = runner.invoke(app, ["capabilities", "--format", "json"])
    assert capabilities.exit_code == 0, capabilities.output
    capability_payload = json.loads(capabilities.stdout)
    assert "doctor" in [item["name"] for item in capability_payload["capabilities"]]
    assert "today" in [item["name"] for item in capability_payload["capabilities"]]


def test_cli_doctor_redacts_database_password(monkeypatch, tmp_path):
    import json
    import studyflow.cli as cli
    from studyflow.config import Settings

    settings = Settings(workspace_root=tmp_path, database_url="mysql+pymysql://studyflow_app:secret-password@127.0.0.1:3306/studyflow")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls, base_dir=None: settings))
    result = CliRunner().invoke(app, ["doctor", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "secret-password" not in result.stdout
    assert "***" in payload["database"]["url"]
    assert payload["database"]["status"] == "unavailable"


def test_today_and_status_share_dashboard_contract(monkeypatch, app_service):
    import json
    import studyflow.cli as cli

    app_service.seed_demo()
    monkeypatch.setattr(cli, "service", lambda: app_service)
    runner = CliRunner()
    today = runner.invoke(app, ["today", "--format", "json"])
    status = runner.invoke(app, ["status", "--format", "json"])
    assert today.exit_code == 0, today.output
    assert status.exit_code == 0, status.output
    today_payload = json.loads(today.stdout)
    status_payload = json.loads(status.stdout)
    assert today_payload["protocol_version"] == "1.2"
    assert today_payload["current_course"] == status_payload["current_course"]
    assert "capabilities" in today_payload
    assert today_payload["database"]["status"] == "not_checked"


def test_cli_reads_engine_submission_and_learning_progress(monkeypatch, app_service):
    import json
    import studyflow.cli as cli
    import studyflow.engine as engine_module
    from studyflow.engine import StudyFlowEngine

    seeded = app_service.seed_demo()
    monkeypatch.setattr(engine_module, "init_db", lambda engine: None)
    monkeypatch.setattr(engine_module, "build_engine", lambda settings: app_service.session_factory.kw["bind"])
    monkeypatch.setattr(cli, "service", lambda: app_service)
    engine = StudyFlowEngine(app_service.settings)
    try:
        submitted = engine.handle({
            "id": 1,
            "method": "submission.submit",
            "params": {"exercise_id": seeded["exercise_id"], "answer_text": "Engine shared answer", "idempotency_key": "engine-cli-submit"},
        })
        assert submitted["ok"] is True
        submission_id = submitted["data"]["id"]

        read_submission = CliRunner().invoke(app, ["submission", "get", "--id", submission_id, "--format", "json"])
        assert read_submission.exit_code == 0, read_submission.output
        submission_payload = json.loads(read_submission.stdout)["submission"]
        assert submission_payload["answer_text"] == "Engine shared answer"
        assert submission_payload["status"] == "WAITING_REVIEW"

        course = app_service.get_course(seeded["course_id"])
        lesson_id = course.lessons[0].id
        saved_progress = engine.handle({
            "id": 2,
            "method": "learning.progress.save",
            "params": {"course_id": seeded["course_id"], "lesson_id": lesson_id, "progress_percent": 42, "last_position": "heading:cli-smoke"},
        })
        assert saved_progress["ok"] is True

        read_course = CliRunner().invoke(app, ["course", "detail", "--id", seeded["course_id"], "--format", "json"])
        assert read_course.exit_code == 0, read_course.output
        course_payload = json.loads(read_course.stdout)
        assert course_payload["lessons"][0]["progress"] == {"progress_percent": 42, "status": "IN_PROGRESS", "last_position": "heading:cli-smoke"}
    finally:
        engine.close()


def test_cli_followup_writes_agent_source(monkeypatch, app_service, tmp_path):
    import json
    import studyflow.cli as cli
    from studyflow.models import Submission
    from sqlalchemy import select
    seeded = app_service.seed_demo()
    first = app_service.submit_answer(seeded["exercise_id"], "第一次答案")
    app_service.write_review(first.id, "需要修正", decision="REVISION_REQUIRED")
    answer = tmp_path / "revision.md"
    answer.write_text("Agent 修正版", encoding="utf-8")
    monkeypatch.setattr(cli, "service", lambda: app_service)
    result = CliRunner().invoke(app, ["submission", "revise", "--parent", first.id, "--file", str(answer), "--format", "json"])
    assert result.exit_code == 0, result.output
    child_id = json.loads(result.stdout)["submission_id"]
    with app_service.session() as db:
        child = db.scalar(select(Submission).where(Submission.id == child_id))
    assert child.source == "AGENT_CLI"

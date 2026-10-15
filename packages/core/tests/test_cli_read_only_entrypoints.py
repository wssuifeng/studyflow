"""Read-only guarantees at the real CLI boundary, not only session mocks."""
import json
import hashlib
import pytest
from pathlib import Path

from typer.testing import CliRunner

from studyflow.cli import app


@pytest.mark.parametrize("command", [["today"], ["course", "detail", "--id", "missing"]])
def test_read_queries_do_not_initialize_an_unselected_empty_cwd(monkeypatch, tmp_path: Path, command):
    import studyflow.infrastructure.config as config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STUDYFLOW_WORKSPACE", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    # Installed binaries default to cwd; reproduce that without touching source data.
    monkeypatch.setattr(config, "default_workspace_root", lambda: tmp_path)
    before = list(tmp_path.iterdir())
    result = CliRunner().invoke(app, [*command, "--format", "json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout or result.stderr)["error_code"] == "WORKSPACE_NOT_INITIALIZED"
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize("command", [
    ["status"], ["plan", "list"], ["plan", "detail", "--id", "missing"],
    ["task", "list"], ["course", "list"], ["course", "detail", "--id", "missing"],
    ["course", "answers", "get", "--id", "missing"],
    ["course", "study-detail", "--study-id", "missing"],
    ["assignment", "queue"], ["submission", "get", "--id", "missing"],
    ["document", "read", "--path", "lesson.md"],
])
def test_read_commands_do_not_create_an_explicit_missing_workspace(monkeypatch, tmp_path, command):
    target = tmp_path / "not-initialized"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    result = CliRunner().invoke(app, [*command, "--format", "json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout or result.stderr)["error_code"] == "WORKSPACE_NOT_INITIALIZED"
    assert not target.exists()


@pytest.mark.parametrize("method,params", [
    ("course.detail", {"course_id": "missing"}),
    ("plan.list", {}), ("course.english.get", {"study_session_id": "missing"}),
])
def test_call_read_method_cannot_initialize(monkeypatch, tmp_path, method, params):
    target = tmp_path / "not-initialized"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    request = tmp_path / "request.json"
    request.write_text(json.dumps(params), encoding="utf-8")
    result = CliRunner().invoke(app, ["call", "--method", method, "--file", str(request), "--format", "json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout or result.stderr)["error_code"] == "WORKSPACE_NOT_INITIALIZED"
    assert not target.exists()


@pytest.mark.parametrize("args", [
    ["version"], ["capabilities"], ["doctor"],
    ["call", "--method", "system.version"],
    ["call", "--method", "system.capabilities"],
    ["call", "--method", "system.schema"],
    ["call", "--method", "system.doctor"],
])
def test_discovery_is_available_without_initialization(monkeypatch, tmp_path, args):
    target = tmp_path / "not-initialized"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    result = CliRunner().invoke(app, [*args, "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"] is True
    assert not target.exists()


def test_existing_workspace_reads_preserve_db_and_detached_results(monkeypatch, app_service):
    seeded = app_service.seed_demo()
    settings = app_service.settings
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(settings.workspace_root))
    monkeypatch.setenv("STUDYFLOW_DATABASE_URL", settings.database_url)
    path = settings.database_path
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    runner = CliRunner()
    for args in [["plan", "list"], ["course", "list"], ["today"],
                 ["course", "detail", "--id", seeded["course_id"]],
                 ["call", "--method", "plan.list"]]:
        result = runner.invoke(app, [*args, "--format", "json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["ok"] is True
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_old_schema_is_reported_without_upgrade(monkeypatch, tmp_path):
    import sqlite3
    target = tmp_path / "existing"
    db = target / ".studyflow" / "studyflow.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE courses (id TEXT PRIMARY KEY)")
    before = db.read_bytes()
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    result = CliRunner().invoke(app, ["course", "list", "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout or result.stderr)["error_code"] == "SCHEMA_UPGRADE_REQUIRED"
    assert db.read_bytes() == before
    assert sorted(p.name for p in target.iterdir()) == [".studyflow"]


def test_readonly_engine_rejects_writes_and_keeps_database(app_service):
    from studyflow.engine import StudyFlowEngine
    seeded = app_service.seed_demo()
    path = app_service.settings.database_path
    before = path.read_bytes()
    engine = StudyFlowEngine(app_service.settings, read_only=True)
    try:
        methods = {cap["method"]: cap for cap in engine.handle({"id": 0, "method": "system.capabilities"})["data"]["capabilities"]}
        assert methods["course.study.open"]["kind"] == "write"
        response = engine.handle({"id": 1, "method": "course.study.open", "params": {"course_id": seeded["course_id"], "idempotency_key": "forbidden-open"}})
        assert response["ok"] is False
        assert response["error"]["code"] == "READ_ONLY_OPERATION"
        assert engine.handle({"id": 2, "method": "plan.list", "params": {}})["ok"] is True
    finally:
        engine.close()
    assert path.read_bytes() == before


def test_unknown_call_does_not_create_workspace(monkeypatch, tmp_path):
    target = tmp_path / "missing"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    result = CliRunner().invoke(app, ["call", "--method", "not.a.method", "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout or result.stderr)["error_code"] == "METHOD_NOT_FOUND"
    assert not target.exists()


@pytest.mark.parametrize("body,code", [("{broken", "INVALID_ARGUMENT"), ("[]", "INVALID_ARGUMENT")])
def test_bad_call_json_does_not_write_diagnostics(monkeypatch, tmp_path, body, code):
    target = tmp_path / "missing"
    request = tmp_path / "request.json"
    request.write_text(body, encoding="utf-8")
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    result = CliRunner().invoke(app, ["call", "--method", "plan.list", "--file", str(request), "--format", "json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout or result.stderr)["error_code"] == code
    assert not target.exists()

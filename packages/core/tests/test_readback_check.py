"""W1 design §6: read-only CLI readback of the learner's active study round vs latest material."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from studyflow.cli import app
from studyflow.config import Settings
from studyflow.db import init_db
from studyflow.services import AppService, new_id
from studyflow.models import Course, Exercise, Lesson
from studyflow.modules.courses.revisions import preview, apply
from test_course_packages import package_file
from test_q234_delivery import upgraded


def build_service(workspace: Path) -> AppService:
    workspace.mkdir(parents=True, exist_ok=True)
    settings = Settings(workspace_root=workspace, database_url=f"sqlite:///{(workspace / 'studyflow.db').as_posix()}")
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    init_db(engine)
    return AppService(settings, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))


def install_markdown_course(service: AppService) -> str:
    plan = service.create_plan_line("合成学习计划")
    with service.session() as db:
        course = Course(id=new_id(), plan_line_id=plan.id, title="回读核对测试")
        db.add(course)
        path = "content/unit-1.md"
        file = service.settings.workspace_root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("# 知识点1\n\n冻结前正文1", encoding="utf-8")
        lesson = Lesson(id=new_id(), course_id=course.id, title="知识点1", position=1, markdown_path=path)
        db.add(lesson)
        db.add(Exercise(id=new_id(), lesson_id=lesson.id, title="练习1", prompt="原题面1", position=1))
        db.flush()
        return course.id


def install_package_course(service: AppService, tmp_path: Path) -> dict:
    service.create_plan_line("Testing")
    return service.import_course_package(package_file(tmp_path, upgraded()))


def use_workspace(monkeypatch, service: AppService) -> None:
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(service.settings.workspace_root))
    monkeypatch.setenv("STUDYFLOW_DATABASE_URL", service.settings.database_url)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(item.relative_to(root)): item.read_bytes() for item in sorted(root.rglob("*")) if item.is_file()}


def invoke_readback(runner: CliRunner, course_id: str, plan_line: str | None = None):
    args = ["course", "readback-check", "--course", course_id, "--format", "json"]
    if plan_line is not None:
        args += ["--plan-line", plan_line]
    return runner.invoke(app, args)


def test_readback_current_round_reads_latest_material(monkeypatch, tmp_path):
    service = build_service(tmp_path / "ws")
    course_id = install_markdown_course(service)
    opened = service.open_course_study(course_id, "open-current")
    sid = opened["study"]["id"]
    use_workspace(monkeypatch, service)
    before = snapshot(tmp_path)
    result = invoke_readback(CliRunner(), course_id)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["course_id"] == course_id
    assert payload["learning_mode"] == "general"
    assert payload["latest_revision"] == 1
    assert payload["active_round"] == {
        "study_session_id": sid,
        "revision": 1,
        "content_hash": opened["study"]["content_hash"],
        "abandoned": False,
    }
    assert payload["current_capture_hash"] == opened["study"]["content_hash"]
    assert payload["readback"] == "current"
    assert payload["next_action"]
    assert snapshot(tmp_path) == before


def test_readback_stale_when_material_edited_without_revision(monkeypatch, tmp_path):
    service = build_service(tmp_path / "ws")
    course_id = install_markdown_course(service)
    sid = service.open_course_study(course_id, "open-stale")["study"]["id"]
    (service.settings.workspace_root / "content/unit-1.md").write_text("# 新版正文", encoding="utf-8")
    use_workspace(monkeypatch, service)
    result = invoke_readback(CliRunner(), course_id)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["readback"] == "stale"
    assert payload["latest_revision"] == 1
    assert payload["active_round"]["study_session_id"] == sid
    assert payload["active_round"]["abandoned"] is False
    assert payload["active_round"]["content_hash"] != payload["current_capture_hash"]
    assert payload["next_action"]


def test_readback_no_active_round_after_revision_apply(monkeypatch, tmp_path):
    service = build_service(tmp_path / "ws")
    installed = install_package_course(service, tmp_path)
    course_id, plan_id = installed["course_id"], installed["plan_id"]
    sid = service.open_course_study(course_id, "reset-open", plan_line_id=plan_id)["study"]["id"]
    data = upgraded()
    data["lessons"][0]["exercises"][0].update(prompt="What does PC point to now?")
    path = tmp_path / "revised.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    check = preview(service.courses, course_id, path, 1)
    applied = apply(service.courses, course_id, path, 1, check["preview_hash"], "readback-reset")
    assert applied["learning_state_reset"] is True
    use_workspace(monkeypatch, service)
    before = snapshot(tmp_path)
    result = invoke_readback(CliRunner(), course_id)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["course_id"] == course_id
    assert payload["readback"] == "no_active_round"
    assert payload["active_round"] is None
    assert payload["latest_revision"] == 2
    assert payload["current_capture_hash"]
    assert snapshot(tmp_path) == before
    scoped = invoke_readback(CliRunner(), course_id, plan_line=plan_id)
    assert scoped.exit_code == 0, scoped.output
    assert json.loads(scoped.stdout)["readback"] == "no_active_round"


def test_readback_missing_course_returns_object_not_found(monkeypatch, tmp_path):
    service = build_service(tmp_path / "ws")
    use_workspace(monkeypatch, service)
    before = snapshot(tmp_path)
    result = invoke_readback(CliRunner(), "missing-course")
    assert result.exit_code == 1
    payload = json.loads(result.stdout or result.stderr)
    assert payload["error_code"] == "OBJECT_NOT_FOUND"
    assert snapshot(tmp_path) == before


def test_readback_plan_line_scope_mismatch(monkeypatch, tmp_path):
    service = build_service(tmp_path / "ws")
    installed = install_package_course(service, tmp_path)
    course_id = installed["course_id"]
    other = service.create_plan_line("别的计划")
    use_workspace(monkeypatch, service)
    result = invoke_readback(CliRunner(), course_id, plan_line=other.id)
    assert result.exit_code == 1
    payload = json.loads(result.stdout or result.stderr)
    assert payload["error_code"] == "SCOPE_MISMATCH"


def test_readback_check_does_not_initialize_workspace(monkeypatch, tmp_path):
    target = tmp_path / "not-initialized"
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(target))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    result = invoke_readback(CliRunner(), "missing")
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout or result.stderr)["error_code"] == "WORKSPACE_NOT_INITIALIZED"
    assert not target.exists()


def test_capabilities_expose_course_readback_check(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("STUDYFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("STUDYFLOW_DATABASE_PATH", raising=False)
    result = CliRunner().invoke(app, ["capabilities", "--format", "json"])
    assert result.exit_code == 0, result.output
    items = {item["name"]: item for item in json.loads(result.stdout)["capabilities"]}
    assert items["course_readback_check"]["kind"] == "read"
    assert "readback-check" in items["course_readback_check"]["command"]

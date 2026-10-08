from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner


def test_course_purge_requires_dry_run_or_confirmation(app_service):
    from studyflow.shared.domain import DomainError

    app_service.seed_demo()
    try:
        app_service.purge_courses()
    except DomainError as exc:
        assert exc.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("destructive purge must require explicit confirmation")


def test_course_purge_removes_course_owned_data_but_keeps_plan(app_service, tmp_path):
    import studyflow.cli as cli

    seeded = app_service.seed_demo()
    course = app_service.get_course(seeded["course_id"])
    source = app_service.settings.workspace_root / course.lessons[0].markdown_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# test course", encoding="utf-8")
    assert source.exists()
    inventory = app_service.preview_course_purge()
    assert inventory["counts"]["courses"] == 1
    assert inventory["counts"]["exercises"] >= 1

    result = app_service.purge_courses(confirm=True)
    assert result["deleted"] is True
    assert app_service.list_courses() == []
    assert not source.exists()
    assert app_service.list_plan_lines()


def test_cli_course_purge_dry_run_is_structured(monkeypatch, app_service):
    import studyflow.cli as cli

    app_service.seed_demo()
    monkeypatch.setattr(cli, "service", lambda **_: app_service)
    result = CliRunner().invoke(cli.app, ["workspace", "purge-courses", "--dry-run", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["counts"]["courses"] == 1


def test_cli_course_purge_without_confirmation_does_not_mutate(monkeypatch, app_service):
    import studyflow.cli as cli

    app_service.seed_demo()
    monkeypatch.setattr(cli, "service", lambda **_: app_service)
    result = CliRunner().invoke(cli.app, ["workspace", "purge-courses", "--format", "json"])
    assert result.exit_code != 0
    assert app_service.list_courses()


def test_course_purge_keeps_markdown_shared_with_remaining_course(app_service):
    from studyflow.modules.courses.models import Course, Lesson
    from studyflow.modules.documents.models import Document
    from studyflow.shared.ids import new_id

    plan = app_service.create_plan_line("Shared Markdown plan")
    shared_path = "content/shared/lesson.md"
    source = app_service.settings.workspace_root / shared_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# shared", encoding="utf-8")
    with app_service.session() as db:
        first = Course(id=new_id(), plan_line_id=plan.id, title="Course A")
        second = Course(id=new_id(), plan_line_id=plan.id, title="Course B")
        db.add_all([first, second])
        db.flush()
        db.add_all([
            Lesson(id=new_id(), course_id=first.id, title="A lesson", position=1, markdown_path=shared_path),
            Lesson(id=new_id(), course_id=second.id, title="B lesson", position=1, markdown_path=shared_path),
            Document(id=new_id(), relative_path=shared_path, document_type="LESSON", status="PRESENT"),
        ])

    preview = app_service.preview_course_purge([first.id])
    assert preview["protected_document_paths"] == [shared_path]
    assert preview["counts"]["documents"] == 0

    result = app_service.purge_courses(confirm=True, course_ids=[first.id])
    assert result["files_removed"] == []
    assert source.exists()
    assert app_service.get_course(first.id) is None
    assert app_service.get_course(second.id) is not None
    with app_service.session() as db:
        assert db.scalar(__import__("sqlalchemy").select(Document).where(Document.relative_path == shared_path)) is not None


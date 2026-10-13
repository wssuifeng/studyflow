from __future__ import annotations

import json
import pytest
from sqlalchemy import select
from typer.testing import CliRunner
from studyflow.shared.domain import DomainError
from studyflow.infrastructure.persistence.base import Base
from studyflow.cli import app
from studyflow.interfaces.cli import runtime
from test_course_study import study_course
from test_plan_notebooks_v2 import entry, write


def seeded(service, course):
    cid, lids, exercises = course
    sid = service.open_course_study(cid, "cleanup-open")["study"]["id"]
    service.save_study_note(sid, lids[0], "旧版草稿", 0, "cleanup-note")
    service.save_study_note(sid, lids[0], "修改后的旧版草稿", 1, "cleanup-note-updated")
    pid = service.get_course(cid).plan_line_id
    write(service, pid, [entry("keep", "新版笔记不能删除", cid, lids[0])])
    service.write_course_answers(cid, [{"exercise_id": exercises[0], "answer_text": "保留真实作答"}],
                                 "DRAFT_SAVE", "cleanup-answer", study_session_id=sid)
    return sid


def protected_state(service):
    with service.session(read_only=True) as db:
        return {table.name: sorted(repr(tuple(row)) for row in db.execute(select(table)))
                for table in Base.metadata.tables.values()
                if table.name not in {"study_notes", "study_note_receipts", "event_logs"}}


def test_preview_is_read_only_without_private_text(app_service, study_course):
    sid = seeded(app_service, study_course)
    state = protected_state(app_service)
    preview = app_service.legacy_note_cleanup()
    assert preview["note_count"] == 1 and preview["receipt_count"] == 2
    assert "草稿" not in json.dumps(preview, ensure_ascii=False)
    assert protected_state(app_service) == state
    assert len(app_service.study_notes(sid)["notes"]) == 1


def test_cleanup_preserves_all_other_data_and_removes_old_receipt_text(app_service, study_course):
    sid = seeded(app_service, study_course)
    before = protected_state(app_service)
    preview = app_service.legacy_note_cleanup()
    result = app_service.legacy_note_cleanup(confirm=True, preview_token=preview["preview_token"])
    assert result["deleted_notes"] == 1 and result["deleted_receipts"] == 2
    assert result["note_count"] == result["receipt_count"] == 0
    assert app_service.study_notes(sid)["notes"] == []
    assert protected_state(app_service) == before
    again = app_service.legacy_note_cleanup(confirm=True, preview_token=result["preview_token"])
    assert again["deleted_notes"] == again["deleted_receipts"] == 0


def test_changed_inventory_refuses_deletion(app_service, study_course):
    sid = seeded(app_service, study_course)
    token = app_service.legacy_note_cleanup()["preview_token"]
    app_service.save_study_note(sid, study_course[1][1], "预览后新增", 0, "new-note")
    with pytest.raises(DomainError, match="清单已变化") as caught:
        app_service.legacy_note_cleanup(confirm=True, preview_token=token)
    assert caught.value.code == "PREVIEW_CHANGED"
    assert app_service.legacy_note_cleanup()["note_count"] == 2


def test_cleanup_rolls_back_both_tables_on_failure(app_service, study_course, monkeypatch):
    seeded(app_service, study_course)
    preview = app_service.legacy_note_cleanup()
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(app_service.learning, "_event", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        app_service.legacy_note_cleanup(confirm=True, preview_token=preview["preview_token"])
    assert app_service.legacy_note_cleanup() == preview


@pytest.mark.parametrize("arguments, code", [
    ([], "CONFIRMATION_REQUIRED"),
    (["--dry-run", "--confirm"], "CONFIRMATION_REQUIRED"),
    (["--confirm"], "PREVIEW_REQUIRED"),
])
def test_cli_confirmation_gates(arguments, code):
    result = CliRunner().invoke(app, ["workspace", "purge-legacy-notes", *arguments, "--format", "json"])
    assert result.exit_code != 0
    assert json.loads(result.output)["error_code"] == code


def test_cli_contract_roundtrip(app_service, study_course, monkeypatch):
    seeded(app_service, study_course)
    calls = []
    def service(**kwargs):
        calls.append(kwargs)
        return app_service
    monkeypatch.setattr(runtime, "service", service)
    runner = CliRunner()
    preview = runner.invoke(app, ["workspace", "purge-legacy-notes", "--dry-run", "--format", "json"])
    assert preview.exit_code == 0, preview.output
    token = json.loads(preview.output)["preview_token"]
    result = runner.invoke(app, ["workspace", "purge-legacy-notes", "--confirm", "--preview-token", token, "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["deleted_notes"] == 1
    assert calls == [{"read_only": True, "existing_only": True}, {"read_only": False, "existing_only": True}]


def test_existing_only_runtime_never_initializes_or_migrates(app_service, monkeypatch):
    import atexit
    releases = []
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(app_service.settings.workspace_root))
    monkeypatch.setenv("STUDYFLOW_DATABASE_URL", app_service.settings.database_url)
    monkeypatch.setattr(atexit, "register", lambda callback: releases.append(callback))
    def fail(*args, **kwargs):
        raise AssertionError("must not initialize or migrate during history removal")
    monkeypatch.setattr(runtime, "init_db", fail)
    try:
        for readonly in (True, False):
            service = runtime.service(read_only=readonly, existing_only=True)
            assert service.legacy_note_cleanup()["note_count"] == 0
    finally:
        for release in releases: release()


def test_cleanup_refuses_read_only_connection(app_service, study_course):
    seeded(app_service, study_course)
    preview = app_service.legacy_note_cleanup()
    app_service.learning.runtime.read_only = True
    try:
        with pytest.raises(DomainError) as caught:
            app_service.legacy_note_cleanup(confirm=True, preview_token=preview["preview_token"])
        assert caught.value.code == "READ_ONLY_OPERATION"
    finally:
        app_service.learning.runtime.read_only = False

from __future__ import annotations
import pytest
from studyflow.domain import DomainError
from test_course_study import study_course

def test_notes_are_persistent_idempotent_and_not_answers(app_service, study_course):
    cid, lessons, ids=study_course
    study=app_service.open_course_study(cid,"notes-open")["study"]["id"]
    saved=app_service.save_study_note(study,lessons[0],"private scratch",0,"note-1")
    assert saved==app_service.save_study_note(study,lessons[0],"private scratch",0,"note-1")
    updated=app_service.save_study_note(study,lessons[0],"revised scratch",1,"note-2")
    assert updated["note"]["version"]==2
    assert app_service.study_notes(study)["notes"][0]["text"]=="revised scratch"
    assert not app_service.agent_queue()["items"]
    assert all(row["draft"] is None for row in app_service.course_answer_sheet(cid,study)["answers"])
    with pytest.raises(DomainError) as caught: app_service.save_study_note(study,lessons[0],"stale",1,"note-stale")
    assert caught.value.code=="VERSION_CONFLICT"
    assert app_service.study_notes(study)["notes"][0]["text"]=="revised scratch"
    with pytest.raises(DomainError) as caught: app_service.save_study_note(study,lessons[0],"different",0,"note-1")
    assert caught.value.code=="IDEMPOTENCY_KEY_CONFLICT"
    with pytest.raises(DomainError): app_service.save_study_note(study,"foreign-lesson","text",0,"foreign")


def test_engine_and_cli_discover_and_round_trip_notes(app_service, study_course, monkeypatch):
    import json
    from typer.testing import CliRunner
    from studyflow.cli import app
    from studyflow.engine import StudyFlowEngine
    from studyflow.interfaces.cli import runtime
    course_id, lesson_ids, _ = study_course
    study_id = app_service.open_course_study(course_id, "notes-contract-open")["study"]["id"]
    engine = StudyFlowEngine(service=app_service)
    methods = {row["method"] for row in engine.handle({"id": 1, "method": "system.capabilities"})["data"]["capabilities"]}
    assert {"course.notes.get", "course.notes.save"}.issubset(methods)
    params = {"study_session_id": study_id, "lesson_id": lesson_ids[0], "text": "synthetic scratch ✅", "expected_version": 0, "idempotency_key": "notes-engine"}
    saved = engine.handle({"id": 2, "method": "course.notes.save", "params": params})
    assert saved["ok"]
    assert engine.handle({"id": 3, "method": "course.notes.save", "params": params})["data"] == saved["data"]
    monkeypatch.setattr(runtime, "service", lambda: app_service)
    monkeypatch.setenv("STUDYFLOW_WORKSPACE", str(app_service.settings.workspace_root))
    path = app_service.settings.workspace_root / "note.txt"
    path.write_text("CLI synthetic scratch", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["course", "notes-save", "--study-id", study_id, "--lesson-id", lesson_ids[0], "--file", str(path), "--expected-version", "1", "--idempotency-key", "notes-cli", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["note"]["version"] == 2
    read = runner.invoke(app, ["course", "notes-get", "--study-id", study_id, "--format", "json"])
    assert read.exit_code == 0 and json.loads(read.output)["notes"][0]["text"] == "CLI synthetic scratch"
    assert not app_service.agent_queue()["items"]


@pytest.mark.parametrize("kind, expected", [
    ("outside", "PATH_OUTSIDE_WORKSPACE"),
    ("missing", "DOCUMENT_NOT_FOUND"),
    ("binary", "UNSUPPORTED_DOCUMENT_TYPE"),
    ("encoding", "DOCUMENT_UNREADABLE"),
    ("oversized", "INVALID_ARGUMENT"),
])
def test_cli_notes_file_boundaries(app_service, study_course, monkeypatch, kind, expected):
    import json
    from typer.testing import CliRunner
    from studyflow.cli import app
    from studyflow.interfaces.cli import runtime
    cid, lessons, _ = study_course
    study_id = app_service.open_course_study(cid, "file-boundary-open")["study"]["id"]
    monkeypatch.setattr(runtime, "service", lambda: app_service)
    root = app_service.settings.workspace_root
    candidate = root / "note.txt"
    if kind == "outside":
        candidate = root.parent / "outside-note.txt"
        candidate.write_text("not permitted", encoding="utf-8")
    elif kind == "binary":
        candidate = root / "note.exe"
        candidate.write_bytes(b"binary")
    elif kind == "encoding":
        candidate.write_bytes(b"\xff\xfeinvalid")
    elif kind == "oversized":
        candidate.write_bytes(b"a" * 800_004)
    result = CliRunner().invoke(app, ["course", "notes-save", "--study-id", study_id,
        "--lesson-id", lessons[0], "--file", str(candidate), "--expected-version", "0",
        "--idempotency-key", "file-boundary", "--format", "json"])
    assert result.exit_code != 0
    assert json.loads(result.output)["error_code"] == expected
    assert not app_service.study_notes(study_id)["notes"]
    assert not app_service.agent_queue()["items"]

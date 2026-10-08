from __future__ import annotations
import pytest
from studyflow.domain import DomainError
from test_course_study import study_course


def test_plan_notebook_is_continuous_scoped_and_not_homework(app_service, study_course):
    cid, lessons, _ = study_course
    plan_id = app_service.get_course(cid).plan_line_id
    sid = app_service.open_course_study(cid, "notebook-round")["study"]["id"]
    app_service.save_study_note(sid, lessons[0], "old scratch stays", 0, "old-scratch")
    empty = app_service.plan_notebook(plan_id)
    assert empty["version"] == 0 and empty["blocks"] == []
    blocks = [{"id":"general", "text":"全计划连续笔记"},
              {"id":"course", "text":"这一课程的理解", "course_id":cid},
              {"id":"lesson", "text":"具体知识点", "course_id":cid, "lesson_id":lessons[1]}]
    saved = app_service.save_plan_notebook(plan_id, blocks, 0, "notebook-first")
    assert len(saved["blocks"]) == 3 and saved["version"] == 1
    assert [b["scope"] for b in saved["blocks"]] == ["PLAN", "COURSE", "LESSON"]
    assert app_service.plan_notebook(plan_id)["blocks"] == saved["blocks"]
    assert app_service.study_notes(sid)["notes"][0]["text"] == "old scratch stays"
    assert not app_service.agent_queue()["items"]
    assert all(a["draft"] is None for a in app_service.course_answer_sheet(cid,sid)["answers"])


def test_notebook_receipts_versions_and_plan_boundary(app_service, study_course):
    cid, lessons, _ = study_course
    pid = app_service.get_course(cid).plan_line_id
    blocks=[{"id":"p1","text":"原始笔记"}]
    saved=app_service.save_plan_notebook(pid,blocks,0,"first-notebook")
    assert saved == app_service.save_plan_notebook(pid,blocks,0,"first-notebook")
    app_service.save_plan_notebook(pid,[{"id":"p1","text":"修改"}],1,"next-notebook")
    with pytest.raises(DomainError) as e: app_service.save_plan_notebook(pid,blocks,1,"stale-notebook")
    assert e.value.code == "VERSION_CONFLICT"
    with pytest.raises(DomainError) as e: app_service.save_plan_notebook(pid,[],0,"first-notebook")
    assert e.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    other=app_service.create_plan_line("其他计划")
    with pytest.raises(DomainError): app_service.save_plan_notebook(other.id,[{"id":"x","text":"no","course_id":cid}],0,"wrong-plan")
    with pytest.raises(DomainError): app_service.save_plan_notebook(pid,[{"id":"x","text":"no","course_id":cid,"lesson_id":"missing"}],2,"wrong-lesson")
    assert app_service.plan_notebook(pid)["blocks"][0]["text"] == "修改"


def test_excerpt_uses_frozen_source_not_live_markdown(app_service, study_course):
    cid, lessons, _ = study_course
    pid=app_service.get_course(cid).plan_line_id
    opened=app_service.open_course_study(cid,"excerpt-open")
    sid=opened["study"]["id"]
    (app_service.settings.workspace_root / "content/unit-1.md").write_text("# 被替换的内容",encoding="utf-8")
    block={"id":"quote1","text":"我的理解","course_id":cid,"lesson_id":lessons[0],"quote":"冻结前正文1","source_study_id":sid}
    saved=app_service.save_plan_notebook(pid,[block],0,"quote-save")
    assert saved["blocks"][0]["content_hash"] == opened["study"]["content_hash"]
    assert saved["blocks"][0]["quote"] == "冻结前正文1"
    assert saved["blocks"][0]["lesson_title"] == "知识点1"
    with pytest.raises(DomainError): app_service.save_plan_notebook(pid,[{**block,"quote":"不在正文里"}],1,"fake-quote")
    assert app_service.plan_notebook(pid)["version"] == 1


def test_notebook_rejects_duplicate_blocks_and_invalid_versions(app_service,study_course):
    cid,_,_=study_course; pid=app_service.get_course(cid).plan_line_id
    for blocks,version in [([{"id":"x","text":"a"},{"id":"x","text":"b"}],0),([],True),([], -1),([{"id":"x","text":123}],0)]:
        with pytest.raises(DomainError): app_service.save_plan_notebook(pid,blocks,version,"invalid")
    assert app_service.plan_notebook(pid)["version"] == 0


def test_engine_cli_notebook_contract(app_service,study_course,monkeypatch):
    import json
    from studyflow.engine import StudyFlowEngine
    from studyflow.cli import app
    from studyflow.interfaces.cli import runtime
    from typer.testing import CliRunner
    cid,_,_=study_course;pid=app_service.get_course(cid).plan_line_id
    engine=StudyFlowEngine(service=app_service)
    methods={c["method"] for c in engine.handle({"id":1,"method":"system.capabilities"})["data"]["capabilities"]}
    assert {"plan.notebook.get","plan.notebook.save"}.issubset(methods)
    saved=engine.handle({"id":2,"method":"plan.notebook.save","params":{"plan_line_id":pid,"blocks":[{"id":"engine","text":"合成笔记"}],"expected_version":0,"idempotency_key":"engine-notebook"}})
    assert saved["ok"] and saved["data"]["version"]==1
    monkeypatch.setattr(runtime,"service",lambda:app_service)
    path=app_service.settings.workspace_root/"notebook.json"
    path.write_text(json.dumps({"blocks":[{"id":"cli","text":"CLI 连续笔记"}]}),encoding="utf-8")
    runner=CliRunner()
    result=runner.invoke(app,["plan","notebook-save","--id",pid,"--file",str(path),"--expected-version","1","--idempotency-key","cli-notebook","--format","json"])
    assert result.exit_code==0,result.output
    assert json.loads(result.output)["version"]==2
    result=runner.invoke(app,["plan","notebook-get","--id",pid,"--format","json"])
    assert result.exit_code==0 and json.loads(result.output)["blocks"][0]["text"]=="CLI 连续笔记"


def test_frozen_excerpt_remains_valid_if_live_lesson_is_removed(app_service, study_course):
    from studyflow.models import Lesson, Exercise
    from sqlalchemy import delete
    cid, lessons, _ = study_course
    pid = app_service.get_course(cid).plan_line_id
    sid = app_service.open_course_study(cid, "removed-source-open")["study"]["id"]
    with app_service.session() as db:
        db.execute(delete(Exercise).where(Exercise.lesson_id == lessons[0]))
        db.execute(delete(Lesson).where(Lesson.id == lessons[0]))
    saved = app_service.save_plan_notebook(pid, [{"id":"frozen", "text":"来源仍是学习时的版本", "course_id":cid,
        "lesson_id":lessons[0], "source_study_id":sid, "quote":"冻结前正文1"}], 0, "removed-source-note")
    assert saved["blocks"][0]["lesson_title"] == "知识点1"

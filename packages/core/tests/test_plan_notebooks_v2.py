from __future__ import annotations
import json
import pytest
from sqlalchemy import select, delete
from test_course_study import study_course
from studyflow.shared.domain import DomainError
from studyflow.modules.learning.notebook.commands import apply
from studyflow.modules.learning.notebook.queries import read
from studyflow.modules.learning.models import PlanNotebook, CourseStudySession


def entry(eid, text, cid=None, lid=None, marks=None):
    node={"type":"text","text":text}
    if marks: node["marks"]=marks
    return {"id":eid,"scope":"LESSON" if lid else "COURSE" if cid else "PLAN","course_id":cid,"lesson_id":lid,"content":[{"type":"paragraph","content":[node]}]}


def setup(app_service, study_course):
    cid,lids,_=study_course
    return app_service.get_course(cid).plan_line_id,cid,lids


def write(app,pid,entries,version=0,key="v2-first",new_sources=None):
    return apply(app.learning,pid,version,key,[{"type":"insert_entry","entry":e} for e in entries],new_sources or [])


def test_v2_insert_replace_hidden_and_replay(app_service,study_course):
    pid,cid,lids=setup(app_service,study_course)
    first=write(app_service,pid,[entry("a","a",cid,lids[0]),entry("b","hidden",cid,lids[1])])
    assert first["format_version"]==2 and first["version"]==1
    ops=[{"type":"replace_entry","entry_id":"a","content":entry("a","new")["content"]}]
    saved=apply(app_service.learning,pid,1,"replace",ops,[])
    assert saved==apply(app_service.learning,pid,1,"replace",ops,[])
    all_rows=read(app_service.learning,pid)["entries"]
    assert [e["id"] for e in all_rows]==["a","b"]
    assert all_rows[1]["content"]==entry("b","hidden")["content"]
    with pytest.raises(DomainError) as ex: apply(app_service.learning,pid,1,"replace",[],[])
    assert ex.value.code=="IDEMPOTENCY_KEY_CONFLICT"
    with pytest.raises(DomainError) as ex: apply(app_service.learning,pid,1,"stale",ops,[])
    assert ex.value.code=="VERSION_CONFLICT"


def test_v1_conversion_and_old_writer_guard(app_service,study_course):
    pid,cid,lids=setup(app_service,study_course)
    sid=app_service.open_course_study(cid,"legacy-source")["study"]["id"]
    blocks=[{"id":"q","quote":"冻结前正文1","text":"我的理解","source_study_id":sid,"course_id":cid,"lesson_id":lids[0]}]
    app_service.save_plan_notebook(pid,blocks,0,"v1")
    preview=read(app_service.learning,pid)
    assert preview["format_version"]==1 and preview["entries"][0]["id"]=="q"
    migrated=apply(app_service.learning,pid,1,"upgrade",[],[])
    assert migrated["version"]==2
    loaded=read(app_service.learning,pid)
    content=loaded["entries"][0]["content"]
    assert [n["content"][0]["text"] for n in content]==["冻结前正文1","我的理解"]
    assert len(loaded["sources"])==1
    with pytest.raises(DomainError) as ex: app_service.save_plan_notebook(pid,[],2,"old-writer")
    assert ex.value.code=="NOTEBOOK_FORMAT_UPGRADE_REQUIRED"
    with app_service.session(read_only=True) as db:
        assert json.loads(db.scalar(select(PlanNotebook)).blocks_json)==blocks or json.loads(db.scalar(select(PlanNotebook)).blocks_json)[0]["text"]=="我的理解"


def test_new_source_is_verified_immutable_and_survives_frozen_cleanup(app_service,study_course):
    pid,cid,lids=setup(app_service,study_course)
    sid=app_service.open_course_study(cid,"new-source")["study"]["id"]
    source={"id":"source1","course_id":cid,"lesson_id":lids[0],"source_study_id":sid,"original":"冻结前正文1"}
    marks=[{"type":"citation","attrs":{"sourceId":"source1","occurrenceId":"occ1"}}]
    write(app_service,pid,[entry("a","冻结前正文1",cid,lids[0],marks)],new_sources=[source])
    with app_service.session() as db:
        db.execute(delete(CourseStudySession).where(CourseStudySession.id==sid))
    ops=[{"type":"replace_entry","entry_id":"a","content":entry("a","自己的改写",marks=marks)["content"]}]
    apply(app_service.learning,pid,1,"edit-after-cleanup",ops,[])
    result=read(app_service.learning,pid)
    assert result["citations"][0]["state"]=="EDITED"
    assert result["sources"][0]["original"]=="冻结前正文1"
    with pytest.raises(DomainError) as ex: apply(app_service.learning,pid,2,"forge",[],[{**source,"original":"伪造"}])
    assert ex.value.code=="NOTEBOOK_SOURCE_IMMUTABLE"


@pytest.mark.parametrize("bad",[
    {"type":"script","text":"x"},
    {"type":"paragraph","attrs":{"onclick":"x"}},
    {"type":"text","text":"x","marks":[{"type":"citation","attrs":{"sourceId":[],"occurrenceId":"o"}}]},
    {"type":"text","text":"x","marks":[{"type":"citation","attrs":None}]},
    {"type":"text","text":"x","marks":[{"type":"link","attrs":{"href":"https://x"}}]},
    {"type":"text","text":"x","marks":[{"type":"citation","attrs":{"sourceId":"missing","occurrenceId":"o"}}]},
])
def test_untrusted_nodes_and_sources_rejected(app_service,study_course,bad):
    pid,_,_=setup(app_service,study_course)
    e=entry("a","a");e["content"]=[bad]
    with pytest.raises(DomainError): write(app_service,pid,[e])
    assert read(app_service.learning,pid)["version"]==0


def test_invalid_batch_rolls_back_all_entries(app_service,study_course):
    pid,cid,lids=setup(app_service,study_course)
    write(app_service,pid,[entry("a","kept")])
    ops=[{"type":"replace_entry","entry_id":"a","content":entry("a","lost")["content"]},{"type":"move_entry","entry_id":"a","scope":"LESSON","course_id":cid,"lesson_id":"missing"}]
    with pytest.raises(DomainError): apply(app_service.learning,pid,1,"bad-batch",ops,[])
    assert read(app_service.learning,pid)["entries"][0]["content"]==entry("a","kept")["content"]
    assert read(app_service.learning,pid)["version"]==1


def test_scope_paging_version_and_anchor(app_service,study_course):
    pid,cid,lids=setup(app_service,study_course)
    write(app_service,pid,[entry("a","a",cid,lids[0]),entry("b","b",cid,lids[1]),entry("p","p")])
    page=read(app_service.learning,pid,limit=1)
    assert page["next_cursor"]==1 and page["total"]==3
    second=read(app_service.learning,pid,offset=1,limit=1,expected_version=1)
    assert second["entries"][0]["id"]=="b"
    assert len(read(app_service.learning,pid,lesson_id=lids[0])["entries"])==1
    apply(app_service.learning,pid,1,"move",[{"type":"move_entry","entry_id":"p","scope":"LESSON","course_id":cid,"lesson_id":lids[0],"after_id":"a"}],[])
    assert [e["id"] for e in read(app_service.learning,pid)["entries"]]==["a","p","b"]
    with pytest.raises(DomainError) as ex: read(app_service.learning,pid,expected_version=1)
    assert ex.value.code=="VERSION_CONFLICT"


def test_duplicate_entry_and_budget_rejected(app_service,study_course):
    pid,_,_=setup(app_service,study_course)
    for entries in ([entry("a","x"),entry("a","y")],[entry("a","x"*200001)]):
        with pytest.raises(DomainError): write(app_service,pid,entries)
    assert read(app_service.learning,pid)["version"]==0


def test_unknown_format_is_readonly(app_service,study_course):
    pid,_,_=setup(app_service,study_course)
    write(app_service,pid,[entry("a","x")])
    with app_service.session() as db: db.scalar(select(PlanNotebook)).format_version=99
    with pytest.raises(DomainError) as ex: apply(app_service.learning,pid,1,"future",[],[])
    assert ex.value.code=="NOTEBOOK_FORMAT_UNSUPPORTED"


def test_engine_cli_v2_contract_and_readonly_paging(app_service,study_course,monkeypatch):
    from studyflow.engine import StudyFlowEngine
    from studyflow.cli import app
    from studyflow.interfaces.cli import runtime
    from typer.testing import CliRunner
    pid,_,_=setup(app_service,study_course)
    engine=StudyFlowEngine(service=app_service)
    caps=engine.handle({"id":1,"method":"system.capabilities"})["data"]
    assert {"plan.notebook.read","plan.notebook.apply"}.issubset({c["method"] for c in caps["capabilities"]})
    assert caps["content"]["notebook"]["legacy_write_v2"] is False
    payload={"operations":[{"type":"insert_entry","entry":entry("cli","可编辑笔记")}],"new_sources":[]}
    monkeypatch.setattr(runtime,"service",lambda **kwargs:app_service)
    path=app_service.settings.workspace_root/"v2.json";path.write_text(json.dumps(payload),encoding="utf-8")
    runner=CliRunner();result=runner.invoke(app,["plan","notebook-apply","--id",pid,"--file",str(path),"--expected-version","0","--idempotency-key","v2-cli","--format","json"])
    assert result.exit_code==0,result.output
    assert json.loads(result.output)["version"]==1
    repeated=runner.invoke(app,["plan","notebook-apply","--id",pid,"--file",str(path),"--expected-version","0","--idempotency-key","v2-cli","--format","json"])
    assert repeated.exit_code==0 and json.loads(repeated.output)==json.loads(result.output)
    readback=runner.invoke(app,["plan","notebook-read","--id",pid,"--entry","cli","--limit","1","--expected-version","1","--format","json"])
    assert readback.exit_code==0 and json.loads(readback.output)["entries"][0]["id"]=="cli"
    bad=engine.handle({"id":2,"method":"plan.notebook.read","params":{"plan_line_id":pid,"limit":101}})
    assert not bad["ok"] and bad["error"]["code"]=="INVALID_ARGUMENT"
    from studyflow.modules.learning.notebook_queries import export
    exported=export(app_service.learning,pid)
    assert exported["document"]["entries"][0]["id"]=="cli" and exported["markdown_lossy"]


def test_source_and_entry_failure_roll_back_together(app_service,study_course):
    from studyflow.modules.learning.models import PlanNotebookSource,PlanNotebookReceipt
    pid,cid,lids=setup(app_service,study_course)
    sid=app_service.open_course_study(cid,"atomic-source")["study"]["id"]
    source={"id":"new","course_id":cid,"lesson_id":lids[0],"source_study_id":sid,"original":"冻结前正文1"}
    with pytest.raises(DomainError): apply(app_service.learning,pid,0,"bad-source-batch",[{"type":"remove_entry","entry_id":"missing"}],[source])
    with app_service.session(read_only=True) as db:
        assert db.scalar(select(PlanNotebookSource)) is None
        assert db.scalar(select(PlanNotebookReceipt).where(PlanNotebookReceipt.idempotency_key=="bad-source-batch")) is None
    assert read(app_service.learning,pid)["version"]==0


def test_0015_upgrade_keeps_legacy_notes_and_backup(tmp_path):
    import sqlite3
    from alembic import command
    from studyflow.config import Settings
    from studyflow.db import build_engine,init_db
    from studyflow.infrastructure.persistence.migrations import _alembic_config
    path=tmp_path/"legacy.db";settings=Settings(workspace_root=tmp_path,database_url=f"sqlite:///{path.as_posix()}")
    command.upgrade(_alembic_config(settings),"0015_english_remediation")
    original=json.dumps([{"id":"old","text":"原始理解","scope":"PLAN"}],ensure_ascii=False)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO plan_lines(id,name) VALUES ('p','合成计划')")
        db.execute("INSERT INTO plan_notebooks(id,plan_line_id,blocks_json,version) VALUES ('n','p',?,3)",(original,))
    engine=build_engine(settings)
    try: init_db(engine)
    finally: engine.dispose()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT blocks_json,version,format_version FROM plan_notebooks").fetchone()==(original,3,1)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0]=="0017_course_experience"
    backups=list(tmp_path.glob("legacy.backup-*.db"));assert len(backups)==1
    with sqlite3.connect(backups[0]) as db: assert db.execute("SELECT blocks_json FROM plan_notebooks").fetchone()[0]==original


def test_english_frozen_sentence_is_a_verified_note_source(app_service,tmp_path):
    from test_english_specialty import install
    course,opened=install(app_service,tmp_path)
    cid=course["course_id"];pid=opened["course"]["plan_line_id"];lid=opened["lessons"][0]["id"];sid=opened["study"]["id"]
    source={"id":"en-source","course_id":cid,"lesson_id":lid,"source_study_id":sid,"original":"I like tea."}
    marks=[{"type":"citation","attrs":{"sourceId":"en-source","occurrenceId":"en-occ"}}]
    write(app_service,pid,[entry("en-note","I like tea.",cid,lid,marks)],new_sources=[source])
    result=read(app_service.learning,pid)
    assert result["sources"][0]["verification"]=="VERIFIED" and result["citations"][0]["state"]=="ORIGINAL"
    apply(app_service.learning,pid,1,"en-case",[{"type":"replace_entry","entry_id":"en-note","content":entry("x","i like tea.",marks=marks)["content"]}],[])
    assert read(app_service.learning,pid)["citations"][0]["state"]=="EDITED"


def test_repository_notebook_example_executes_as_documented(app_service,tmp_path):
    from pathlib import Path
    repo=Path(__file__).resolve().parents[3]
    example=json.loads((repo/"skills/studyflow-agent/examples/notebook-v2-apply.json").read_text(encoding="utf-8"))
    pid=app_service.create_plan_line("Skill合成例子").id
    result=apply(app_service.learning,pid,0,"skill-example",example["operations"],example["new_sources"],source="AGENT_CLI")
    assert result["version"]==1 and read(app_service.learning,pid)["entries"][0]["id"]=="authorized-note-1"


def test_v2_workspace_backup_restores_structure_sources_and_version(app_service,study_course,tmp_path):
    from studyflow.infrastructure.persistence.migrations import _alembic_stamp
    from studyflow.workspace import export_workspace,restore_workspace
    from studyflow.config import Settings
    from studyflow.db import build_engine,build_session_factory,init_db
    from studyflow.services import AppService
    pid,cid,lids=setup(app_service,study_course)
    sid=app_service.open_course_study(cid,"backup-source")["study"]["id"]
    source={"id":"backup-source","course_id":cid,"lesson_id":lids[0],"source_study_id":sid,"original":"冻结前正文1"}
    marks=[{"type":"citation","attrs":{"sourceId":"backup-source","occurrenceId":"backup-occ"}}]
    write(app_service,pid,[entry("backup-entry","冻结前正文1",cid,lids[0],marks)],new_sources=[source])
    _alembic_stamp(app_service.settings,"0016_notebook_document")
    archive=tmp_path/"notebook-backup.zip"
    exported=export_workspace(app_service.settings,archive)
    assert exported["schema_revision"]=="0016_notebook_document"
    restored=tmp_path/"restored-notebook";restore_workspace(archive,restored)
    settings=Settings(workspace_root=restored,database_url=f"sqlite:///{(restored/'.studyflow/studyflow.db').as_posix()}")
    engine=build_engine(settings)
    try:
        init_db(engine);service=AppService(settings,build_session_factory(engine))
        data=read(service.learning,pid)
        assert data["version"]==1 and data["entries"][0]["id"]=="backup-entry"
        assert data["sources"][0]["original"]=="冻结前正文1"
    finally:engine.dispose()

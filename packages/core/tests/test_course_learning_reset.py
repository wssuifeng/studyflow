"""Authorized maintenance uses disposable synthetic workspaces, never learner data."""
import json
import pytest
from sqlalchemy import select
from typer.testing import CliRunner
from studyflow.cli import app
from studyflow.shared.domain import DomainError
from studyflow.modules.learning.models import CourseStudySession, Submission
from studyflow.modules.learning.reset import preview, apply
from studyflow.modules.reviews.queue_queries import summary
from test_material_reset import install, revise
from test_course_answers import multi_course
from test_english_specialty import install as install_english


def submitted(service, opened):
    answers=[{"exercise_id":e["id"],"answer_text":"Synthetic answer"}
             for lesson in opened["lessons"] for e in lesson["exercises"]]
    return service.write_course_answers(opened["course"]["id"],answers,"SUBMIT","before-reset-submit",
                                        study_session_id=opened["study"]["id"])


def reset(service, course_id, key="reset-test", **kwargs):
    info=preview(service.learning,course_id)
    return apply(service.learning,course_id,info["state_hash"],info["content_hash"],key,confirm=True,**kwargs)


def test_reset_submitted_stale_round_without_review_and_preserves_notes(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);cid=result["course_id"];sid=opened["study"]["id"]
    submitted(app_service,opened)
    app_service.save_study_note(sid,opened["lessons"][0]["id"],"keep note",0,"keep-note")
    # Simulate content already published by a pre-W2 installation: current source differs from snapshot.
    path=tmp_path/opened["lessons"][0]["markdown_path"]
    path.write_text(path.read_text(encoding="utf-8").replace("CPU executes instructions.","Updated explanation."),encoding="utf-8")
    assert app_service.course_study_detail(sid)["study"]["source_changed"]
    assert summary(app_service.reviews,course_id=cid)["counts"]["WAITING_REVIEW"]
    out=reset(app_service,cid)
    assert out["learning_state_reset"] and out["study_session_id"]!=sid
    new=app_service.course_study_detail(out["study_session_id"])
    assert new["study"]["source_changed"] is False and new["course"]["study_status"]=="IN_PROGRESS"
    assert all(not row.get("submission") for row in app_service.course_answer_sheet(cid,study_session_id=out["study_session_id"])["answers"])
    assert summary(app_service.reviews,course_id=cid)["items"]==[]
    assert not any(x["course_id"]==cid for x in app_service.agent_queue()["items"])
    assert any(n["text"]=="keep note" for n in app_service.study_notes(sid)["notes"])
    with app_service.session(read_only=True) as db:
        assert db.scalar(select(Submission).where(Submission.study_session_id==sid)) is not None


def test_preview_readonly_and_confirm_required(app_service,tmp_path,monkeypatch):
    result,opened=install(app_service,tmp_path)
    import studyflow.infrastructure.leases as leases
    with monkeypatch.context() as m:
        m.setattr(leases,"workspace_lease",lambda *a: (_ for _ in ()).throw(AssertionError("preview took lease")))
        info=preview(app_service.learning,result["course_id"])
    with pytest.raises(DomainError) as e:
        apply(app_service.learning,result["course_id"],info["state_hash"],info["content_hash"],"not-confirmed")
    assert e.value.code=="CONFIRMATION_REQUIRED"
    assert app_service.course_study_detail(opened["study"]["id"])["study"]["is_current"]


def test_reset_replay_never_resets_new_round_and_conflicts_on_key_reuse(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);cid=result["course_id"]
    info=preview(app_service.learning,cid)
    args=(app_service.learning,cid,info["state_hash"],info["content_hash"],"once")
    first=apply(*args,confirm=True)
    eid=opened["lessons"][0]["exercises"][0]["id"]
    app_service.write_course_answers(cid,[{"exercise_id":eid,"answer_text":"new draft"}],"DRAFT_SAVE","after-reset",study_session_id=first["study_session_id"])
    assert apply(*args,confirm=True)==first
    assert app_service.course_study_detail(first["study_session_id"])["study"]["is_current"]
    info2=preview(app_service.learning,cid)
    with pytest.raises(DomainError) as e:
        apply(app_service.learning,cid,info2["state_hash"],info2["content_hash"],"once",confirm=True)
    assert e.value.code=="IDEMPOTENCY_KEY_CONFLICT"


def test_reset_rejects_writes_after_preview_without_partial_reset(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);cid=result["course_id"];sid=opened["study"]["id"]
    info=preview(app_service.learning,cid)
    eid=opened["lessons"][0]["exercises"][0]["id"]
    app_service.write_course_answers(cid,[{"exercise_id":eid,"answer_text":"concurrent draft"}],"DRAFT_SAVE","racing-save",study_session_id=sid)
    with pytest.raises(DomainError) as e:
        apply(app_service.learning,cid,info["state_hash"],info["content_hash"],"stale-reset",confirm=True)
    assert e.value.code=="VERSION_CONFLICT"
    assert app_service.course_study_detail(sid)["study"]["is_current"]


def test_reset_preserves_other_course_and_rejects_late_write(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);other,other_open=install_english(app_service,tmp_path)
    reset(app_service,result["course_id"])
    assert app_service.course_study_detail(other_open["study"]["id"])["study"]["is_current"]
    with pytest.raises(DomainError) as e:
        app_service.save_study_progress(opened["study"]["id"],opened["lessons"][0]["id"],80,"late",expected_version=1)
    assert e.value.code=="STUDY_ROUND_SUPERSEDED"


def test_reset_english_with_saved_and_checked_answers(app_service,tmp_path):
    result,opened=install_english(app_service,tmp_path);sid=opened["study"]["id"]
    eid=opened["lessons"][0]["exercises"][0]["id"]
    save=app_service.english.save(sid,eid,"I lik tea",0,"en-save")
    app_service.english.check(sid,eid,save["answer_version"],"en-check")
    out=reset(app_service,result["course_id"])
    fresh=app_service.english.get(out["study_session_id"])
    assert fresh["position"]==0 and not fresh["completed"]
    assert all(i["answer_text"]=="" and not i["matched"] for i in fresh["items"])


def test_material_apply_also_clears_current_review_queue(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);submitted(app_service,opened)
    revise(app_service,tmp_path,result["course_id"],1,"new-material",mutate=lambda d:d["lessons"][0]["blocks"][0]["sections"][0].update(body="New body"))
    assert summary(app_service.reviews,course_id=result["course_id"])["items"]==[]
    assert not any(i["course_id"]==result["course_id"] for i in app_service.agent_queue()["items"])


def test_reset_cli_dryrun_and_apply(app_service,tmp_path,monkeypatch):
    result,_=install(app_service,tmp_path);cid=result["course_id"]
    import studyflow.interfaces.cli.runtime as runtime
    monkeypatch.setattr(runtime,"service",lambda **kw:app_service)
    runner=CliRunner()
    dry=runner.invoke(app,["course","reset-learning","--id",cid,"--dry-run","--format","json"])
    assert dry.exit_code==0,dry.output
    info=json.loads(dry.output)
    done=runner.invoke(app,["course","reset-learning","--id",cid,"--confirm","--state-hash",info["state_hash"],"--content-hash",info["content_hash"],"--idempotency-key","cli-reset","--format","json"])
    assert done.exit_code==0,done.output
    assert json.loads(done.output)["learning_state_reset"]


def test_purge_cli_supports_explicit_course_scope(app_service,tmp_path,monkeypatch):
    result,_=install(app_service,tmp_path);other,_=install_english(app_service,tmp_path)
    import studyflow.interfaces.cli.runtime as runtime
    monkeypatch.setattr(runtime,"service",lambda **kw:app_service)
    runner=CliRunner()
    dry=runner.invoke(app,["workspace","purge-courses","--id",result["course_id"],"--dry-run","--format","json"])
    assert dry.exit_code==0,dry.output
    assert json.loads(dry.output)["course_ids"]==[result["course_id"]]
    assert app_service.course_detail(other["course_id"])


def test_reset_legacy_without_round_does_not_reuse_answers(app_service,multi_course):
    from test_course_answers import entries
    cid,ids=multi_course
    (app_service.settings.workspace_root/"content").mkdir(exist_ok=True)
    (app_service.settings.workspace_root/"content/second.md").write_text("# Synthetic lesson\nReadable body.",encoding="utf-8")
    app_service.write_course_answers(cid,entries(ids),"SUBMIT","legacy-submit")
    out=reset(app_service,cid)
    assert all(not r.get("submission") for r in app_service.course_answer_sheet(cid,study_session_id=out["study_session_id"])["answers"])
    assert not any(x["course_id"]==cid for x in app_service.agent_queue()["items"])
    assert summary(app_service.reviews,course_id=cid)["items"]==[]


def test_unreadable_latest_material_never_seals_old_round(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);cid=result["course_id"];sid=opened["study"]["id"]
    info=preview(app_service.learning,cid)
    (tmp_path/opened["lessons"][0]["markdown_path"]).unlink()
    with pytest.raises(DomainError):
        apply(app_service.learning,cid,info["state_hash"],info["content_hash"],"unreadable",confirm=True)
    with app_service.session(read_only=True) as db:
        assert db.get(CourseStudySession,sid).abandoned_at is None


def test_reader_restart_opt_in_can_reset_submitted_round(app_service,tmp_path):
    from studyflow.modules.learning.restart import preview as restart_preview, restart
    result,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    submitted(app_service,opened)
    info=restart_preview(app_service.learning,sid,reset_current_state=True)
    assert info["can_restart"] and info["expected_state_hash"]
    args=dict(study_session_id=sid,expected_version=info["expected_version"],
        expected_content_hash=info["expected_content_hash"],expected_state_hash=info["expected_state_hash"],
        reset_current_state=True,idempotency_key="reader-reset")
    fresh=restart(app_service.learning,**args)
    assert fresh["study"]["is_current"] and fresh["study"]["id"]!=sid
    assert restart(app_service.learning,**args)["study"]["id"]==fresh["study"]["id"]


def test_actual_scoped_purge_keeps_other_course_and_plan(app_service,tmp_path):
    result,opened=install(app_service,tmp_path);other,other_open=install_english(app_service,tmp_path)
    submitted(app_service,opened)
    app_service.save_plan_notebook(result["plan_id"],[{"id":"personal","text":"keep plan note"}],0,"plan-note-purge")
    out=app_service.purge_courses(confirm=True,course_ids=[result["course_id"]])
    assert out["deleted"]
    assert app_service.course_detail(other["course_id"])
    assert app_service.course_study_detail(other_open["study"]["id"])["study"]["is_current"]
    assert "keep plan note" in json.dumps(app_service.plan_notebook(result["plan_id"]))
    with app_service.session(read_only=True) as db:
        assert db.scalar(select(Submission).where(Submission.study_session_id==opened["study"]["id"])) is None


def test_engine_reset_discovery_and_schema_are_real():
    from studyflow.interfaces.engine.protocol import all_capabilities
    from studyflow.interfaces.engine.schemas import validate,schemas
    methods={i["method"]:i["kind"] for i in all_capabilities()}
    assert methods["course.learning.reset.preview"]=="read"
    assert methods["course.learning.reset.apply"]=="write"
    assert "expected_state_hash" in schemas("course.learning.reset.apply")["methods"]["course.learning.reset.apply"]["properties"]
    with pytest.raises(DomainError):validate("course.learning.reset.apply",{"course_id":"c","confirm":True})


def test_course_update_cli_overwrites_and_resets_submitted_round(app_service,tmp_path,monkeypatch):
    from test_course_packages import package_file
    from test_q234_delivery import upgraded
    result,opened=install(app_service,tmp_path);submitted(app_service,opened)
    data=upgraded();data["lessons"][0]["blocks"][0]["sections"][0]["body"]="Replacement content."
    file=package_file(tmp_path,data)
    import studyflow.interfaces.cli.runtime as runtime
    monkeypatch.setattr(runtime,"service",lambda **kw:app_service)
    runner=CliRunner();base=["--id",result["course_id"],"--file",str(file),"--expected-revision","1"]
    proposal=runner.invoke(app,["course","update-preview",*base,"--format","json"])
    assert proposal.exit_code==0,proposal.output
    receipt=runner.invoke(app,["course","update-apply",*base,"--preview-hash",json.loads(proposal.output)["preview_hash"],"--idempotency-key","replace-cli","--format","json"])
    assert receipt.exit_code==0,receipt.output
    assert json.loads(receipt.output)["learning_state_reset"]
    assert not summary(app_service.reviews,course_id=result["course_id"])["items"]


def test_omitted_study_id_cannot_write_into_sealed_round(app_service,tmp_path):
    result,opened=install(app_service,tmp_path)
    revise(app_service,tmp_path,result["course_id"],1,"seal",mutate=lambda d:d["lessons"][0]["blocks"][0]["sections"][0].update(body="updated"))
    with pytest.raises(DomainError) as e:
        app_service.write_course_answers(result["course_id"],[{"exercise_id":opened["lessons"][0]["exercises"][0]["id"],"answer_text":"late"}],"DRAFT_SAVE","late-without-study")
    assert e.value.code=="STUDY_ROUND_SUPERSEDED"


def test_unchanged_republish_does_not_make_active_material_stale(app_service,tmp_path):
    result,opened=install(app_service,tmp_path)
    out=revise(app_service,tmp_path,result["course_id"],1,"unchanged-no-revision")
    assert out["learning_state_reset"] is False
    assert out["revision"]==1
    assert not app_service.course_study_detail(opened["study"]["id"])["study"]["source_changed"]
    replay=revise(app_service,tmp_path,result["course_id"],1,"unchanged-no-revision")
    assert replay==out


def test_material_replacement_with_pre_round_answers_never_reuses_them(app_service,tmp_path):
    from test_q234_delivery import upgraded
    from test_course_packages import package_file
    app_service.create_plan_line("Testing")
    result=app_service.import_course_package(package_file(tmp_path,upgraded()))
    detail=app_service.course_detail(result["course_id"])
    eid=detail["lessons"][0]["exercises"][0]["id"]
    app_service.write_course_answers(result["course_id"],[{"exercise_id":eid,"answer_text":"legacy"}],"SUBMIT","pre-round")
    out=revise(app_service,tmp_path,result["course_id"],1,"legacy-replace",mutate=lambda d:d["lessons"][0]["blocks"][0]["sections"][0].update(body="new"))
    assert out["learning_state_reset"]
    opened=app_service.open_course_study(result["course_id"],"after-legacy-replace")
    assert opened["study"]["revision"]==2
    assert all(not i["submission"] for i in app_service.course_answer_sheet(result["course_id"])["answers"])
    assert not summary(app_service.reviews,course_id=result["course_id"])["items"]

"""SF regression scenarios use synthetic data only."""
import copy
import json
import pytest
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.content import validate_package
from studyflow.modules.learning.models import Submission, SubmissionWriteReceipt


def package(count=1):
    return {"schema":"studyflow.course-package/1", "package_id":"synthetic-course", "plan_line":"Synthetic plan", "course":{"title":"Synthetic course"}, "lessons":[{"id":f"l-{i}","title":f"Unit {i}","blocks":[{"id":"concept","type":"concept","title":"Concept","body":"Synthetic teaching material."}],"exercises":[{"id":f"e-{j}","title":f"Question {j}","prompt":"Explain a synthetic concept."} for j in range(min(100,count-i*100))]} for i in range((count+99)//100)]}

@pytest.fixture
def synthetic(app_service, tmp_path):
    app_service.create_plan_line("Synthetic plan")
    path=tmp_path/"course.json"; path.write_text(json.dumps(package()),encoding="utf-8")
    result=app_service.import_course_package(path)
    study=app_service.open_course_study(result["course_id"],"open-synthetic")
    return result["course_id"],study["study"]["id"],study["lessons"][0]["exercises"][0]["id"]

def test_sequential_followups_have_one_effective_leaf(app_service, synthetic):
    c,s,e=synthetic
    original=app_service.submit_answer(e,"original",idempotency_key="first")
    app_service.write_review(original.id,"Fix",decision="REVISION_REQUIRED",idempotency_key="review")
    child=app_service.revise_submission(original.id,"corrected",idempotency_key="child")
    assert app_service.revise_submission(original.id,"corrected",idempotency_key="child").id==child.id
    with pytest.raises(DomainError) as failure:
        app_service.revise_submission(original.id,"different",idempotency_key="second-child")
    assert failure.value.code in {"VERSION_CONFLICT","SUBMISSION_BRANCH_CONFLICT"}
    assert len(app_service.agent_queue()["waiting_review"])==1
    assert app_service.course_answer_sheet(c,s)["answers"][0]["submission"]["id"]==child.id

@pytest.mark.parametrize("operation",["DRAFT_SAVE","SUBMIT","LEGACY_SUBMIT"])
def test_single_write_replay_checks_payload(app_service,synthetic,operation):
    c,s,e=synthetic
    fn={"DRAFT_SAVE":app_service.save_submission_draft,"SUBMIT":app_service.submit_submission,"LEGACY_SUBMIT":app_service.submit_answer}[operation]
    row=fn(exercise_id=e,answer_text="first",idempotency_key="payload")
    assert fn(exercise_id=e,answer_text="first",idempotency_key="payload").id==row.id
    with pytest.raises(DomainError) as failure:
        fn(exercise_id=e,answer_text="changed",idempotency_key="payload")
    assert failure.value.code=="IDEMPOTENCY_KEY_CONFLICT"

def test_file_sqlite_keeps_temp_store_in_memory(app_service):
    bind = app_service.session_factory.kw["bind"]
    with bind.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA temp_store").scalar_one() == 2


def test_package_limit_is_total_not_per_lesson():
    assert validate_package(package(500))
    with pytest.raises(DomainError,match="500"):
        validate_package(package(501))

def test_legacy_receipt_is_not_falsely_verified(app_service,synthetic):
    c,s,e=synthetic
    row=app_service.save_submission_draft(e,"original")
    with app_service.session() as db:
        db.add(SubmissionWriteReceipt(id="legacy",idempotency_key="unknown",operation="DRAFT_SAVE",submission_id=row.id))
    with pytest.raises(DomainError) as failure:
        app_service.save_submission_draft(e,"changed",idempotency_key="unknown")
    assert failure.value.code=="IDEMPOTENCY_UNVERIFIABLE"


def test_structured_feedback_quotes_original_and_retest_freezes(app_service,synthetic):
    from studyflow.modules.reviews.retests import publish
    c,s,e=synthetic
    first=app_service.submit_answer(e,"original synthetic statement",idempotency_key="issue-answer")
    issue={"quote":"invented","location":"第1句","reason":"原因","guidance":"方向","next_action":"修正"}
    with pytest.raises(DomainError) as failure:
        app_service.write_review(first.id,"检查",decision="REVISION_REQUIRED",issues=[issue],idempotency_key="bad-review")
    assert failure.value.code=="REVIEW_QUOTE_MISMATCH"
    issue["quote"]="original"
    app_service.write_review(first.id,"新题复测",decision="RETEST_REQUIRED",issues=[issue],idempotency_key="real-review")
    assert app_service.course_answer_sheet(c,s)["answers"][0]["action"]=="WAITING_RETEST_TASK"
    task=publish(app_service.reviews,first.id,"New question","A different frozen question","Check understanding","retest-publish",agent_reference="PRIVATE RUBRIC")
    assert "agent_reference" not in json.dumps(task)
    assert publish(app_service.reviews,first.id,"New question","A different frozen question","Check understanding","retest-publish",agent_reference="PRIVATE RUBRIC")==task
    with pytest.raises(DomainError):publish(app_service.reviews,first.id,"Changed","Different","Check understanding","another-key")
    sheet=app_service.course_answer_sheet(c,s)
    assert sheet["answers"][0]["retest_task"]["prompt"]=="A different frozen question"
    assert "PRIVATE RUBRIC" not in json.dumps(sheet,default=str)
    submitted=app_service.write_course_answers(c,[{"exercise_id":e,"parent_submission_id":first.id,"retest_task_id":task["id"],"answer_text":"new answer"}],"SUBMIT","new-test-answer",study_session_id=s)
    detail=app_service.submission_detail(submitted["submissions"][0]["id"])
    assert detail["retest_task"]["prompt"]==task["prompt"]
    app_service.write_review(detail["id"],"Passed",decision="PASSED",idempotency_key="pass-retest")
    assert app_service.course_study_detail(s)["course"]["study_status"]=="PASSED"


def test_agent_summary_is_small_context_is_deduplicated(app_service,synthetic):
    from studyflow.modules.reviews.queue_queries import summary,context
    c,s,e=synthetic
    row=app_service.submit_answer(e,"Long enough answer"*100,idempotency_key="queue-small")
    queue=summary(app_service.reviews,role="agent")
    assert queue["items"][0]["action"]=="REVIEW"
    assert "answer_text" not in queue["items"][0]
    assert "study_context" not in json.dumps(queue)
    assert len(json.dumps(queue).encode())<100*1024
    read=context(app_service,[row.id,row.id])
    assert len(read["items"])==len(read["contexts"])==1


def test_course_revision_preserves_course_and_frozen_round(app_service,synthetic,tmp_path):
    from studyflow.modules.courses.revisions import preview,apply
    from studyflow.modules.courses.models import Course
    c,s,e=synthetic
    before=app_service.course_study_detail(s)
    data=package(2);data["course"]["title"]="Revised title";data["lessons"][0]["blocks"][0]["body"]="Revised teaching material"
    path=tmp_path/"revision.json";path.write_text(json.dumps(data),encoding="utf-8")
    check=preview(app_service.courses,c,path,1)
    result=apply(app_service.courses,c,path,1,check["preview_hash"],"publish-two")
    assert result["revision"]==2
    assert apply(app_service.courses,c,path,1,check["preview_hash"],"publish-two")==result
    assert app_service.course_detail(c)["lessons"][0]["exercises"][0]["id"]==e
    assert len(app_service.course_detail(c)["lessons"][0]["exercises"])==2
    after=app_service.course_study_detail(s)
    assert after["study"]["content_hash"]==before["study"]["content_hash"]
    assert after["lessons"][0]["exercises"][0]["prompt"]==before["lessons"][0]["exercises"][0]["prompt"]
    assert len(after["lessons"][0]["exercises"])==1
    with app_service.session() as db:assert len(db.scalars(select(Course)).all())==1
    check=preview(app_service.courses,c,path,2)
    data["course"]["title"]="Modified after preview";path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(DomainError) as failure:apply(app_service.courses,c,path,2,check["preview_hash"],"stale-preview")
    assert failure.value.code=="PREVIEW_CHANGED"


def test_plan_management_replays_and_preserves_evidence(app_service,synthetic):
    from studyflow.modules.planning.management import edit_plan
    from studyflow.modules.planning.models import PlanLine,CourseScheduleItem
    c,s,e=synthetic
    plan=app_service.get_plan_line("Synthetic plan")
    pause=edit_plan(app_service.planning,plan.id,1,"pause-plan","UPDATE",{"status":"PAUSED"})
    assert edit_plan(app_service.planning,plan.id,1,"pause-plan","UPDATE",{"status":"PAUSED"})==pause
    with pytest.raises(DomainError):edit_plan(app_service.planning,plan.id,1,"stale-plan","UPDATE",{"status":"ACTIVE"})
    edit_plan(app_service.planning,plan.id,2,"schedule-plan","SCHEDULE",{"course_id":c,"date":"2026-10-03"})
    with app_service.session() as db:row=db.scalar(select(CourseScheduleItem));identifier=row.id
    edit_plan(app_service.planning,plan.id,3,"reschedule-plan","RESCHEDULE",{"schedule_id":identifier,"date":"2026-10-04"})
    edit_plan(app_service.planning,plan.id,4,"cancel-plan","CANCEL_SCHEDULE",{"schedule_id":identifier})
    assert app_service.course_study_detail(s)["course"]["study_status"]=="IN_PROGRESS"
    assert app_service.get_plan_line(plan.id).status=="PAUSED"


def test_maintenance_lease_excludes_live_engine(app_service,synthetic,tmp_path):
    from studyflow.infrastructure.leases import workspace_lease
    from studyflow.engine import StudyFlowEngine
    engine=StudyFlowEngine(service=app_service)
    try:
        with pytest.raises(DomainError) as failure:
            with workspace_lease(app_service.settings.workspace_root,exclusive=True):pass
        assert failure.value.code=="WORKSPACE_MAINTENANCE_BUSY"
    finally:engine.close()
    with workspace_lease(app_service.settings.workspace_root,exclusive=True):pass


def test_new_schema_refused_before_old_code_writes(tmp_path):
    from sqlalchemy import create_engine,text
    from studyflow.db import init_db
    engine=create_engine("sqlite:///"+str(tmp_path/"future.db"))
    with engine.begin() as db:
        db.execute(text("CREATE TABLE alembic_version(version_num TEXT)"));db.execute(text("INSERT INTO alembic_version VALUES('9999_future')"))
    with pytest.raises(DomainError) as failure:init_db(engine)
    assert failure.value.code=="NEWER_SCHEMA_UNSUPPORTED"
    engine.dispose()


def test_concurrent_followups_do_not_fork(app_service,synthetic):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.exc import SQLAlchemyError
    c,s,e=synthetic
    parent=app_service.submit_answer(e,"original",idempotency_key="parallel-first")
    app_service.write_review(parent.id,"Fix",decision="REVISION_REQUIRED")
    barrier=Barrier(2)
    def run(i):
        barrier.wait()
        try:return app_service.revise_submission(parent.id,f"correction {i}",idempotency_key=f"parallel-{i}").id
        except (DomainError,SQLAlchemyError):return None
    with ThreadPoolExecutor(2) as executor:results=list(executor.map(run,[1,2]))
    assert sum(r is not None for r in results)==1
    assert len(app_service.submission_detail(parent.id)["children"])==1


def test_whole_course_500_boundary_and_501_no_registration(app_service,tmp_path):
    from studyflow.modules.courses.models import Course
    app_service.create_plan_line("Synthetic plan")
    path=tmp_path/"capacity.json";path.write_text(json.dumps(package(501)),encoding="utf-8")
    with pytest.raises(DomainError):app_service.import_course_package(path)
    with app_service.session() as db:assert db.scalar(select(Course.id)) is None
    assert not list((tmp_path/"content").glob("course-packages/*"))
    path.write_text(json.dumps(package(500)),encoding="utf-8")
    imported=app_service.import_course_package(path);study=app_service.open_course_study(imported["course_id"],"capacity-open")
    answers=[{"exercise_id":ex["id"],"answer_text":"synthetic answer"} for l in study["lessons"] for ex in l["exercises"]]
    result=app_service.write_course_answers(imported["course_id"],answers,"SUBMIT","capacity-submit",study_session_id=study["study"]["id"])
    assert len(result["submissions"])==500


def test_twenty_question_queue_volume_and_shared_context(app_service,tmp_path):
    from studyflow.modules.reviews.queue_queries import summary,context
    app_service.create_plan_line("Synthetic plan")
    data=package(20);data["lessons"][0]["blocks"][0]["body"]="Synthetic long material. "*500
    path=tmp_path/"volume.json";path.write_text(json.dumps(data),encoding="utf-8")
    course=app_service.import_course_package(path);study=app_service.open_course_study(course["course_id"],"volume-open")
    answers=[{"exercise_id":ex["id"],"answer_text":"Synthetic answer"} for l in study["lessons"] for ex in l["exercises"]]
    written=app_service.write_course_answers(course["course_id"],answers,"SUBMIT","volume-submit",study_session_id=study["study"]["id"])
    queue=summary(app_service.reviews,role="agent")
    assert len(queue["items"])==20 and len(json.dumps(queue).encode())<=100*1024
    contexts=context(app_service,[s["id"] for s in written["submissions"]])
    assert len(contexts["contexts"])==1
    assert all("study_context" not in i for i in contexts["items"])


def test_notebook_search_export_and_source_never_open_round(app_service,synthetic):
    from studyflow.modules.learning.notebook_queries import search,export,source
    from studyflow.modules.learning.models import CourseStudySession
    from sqlalchemy import func
    c,s,e=synthetic
    plan=app_service.get_plan_line("Synthetic plan")
    app_service.save_plan_notebook(plan.id,[{"id":"note","text":"中文连续笔记"}],0,"note-save")
    assert search(app_service.learning,plan.id,"中文")["count"]==1
    assert "中文连续笔记" in export(app_service.learning,plan.id)["markdown"]
    lesson=app_service.course_study_detail(s)["lessons"][0]["id"]
    assert source(app_service.learning,s,lesson)["readonly"]
    with app_service.session() as db:assert db.scalar(select(func.count(CourseStudySession.id)))==1


def test_legacy_branch_resolution_keeps_both_records(app_service,synthetic):
    from studyflow.modules.learning.branches import resolve
    from studyflow.shared.ids import new_id
    c,s,e=synthetic
    parent=app_service.submit_answer(e,"original",idempotency_key="branch-parent")
    app_service.write_review(parent.id,"修正",decision="REVISION_REQUIRED")
    ids=[]
    with app_service.session() as db:
        for n in range(2):
            child=Submission(id=new_id(),exercise_id=e,study_session_id=s,parent_submission_id=parent.id,status="WAITING_REVIEW",answer_text=f"old correction {n}",attempt_number=2,attempt_kind="REVISION")
            db.add(child);ids.append(child.id)
    with pytest.raises(DomainError) as failure:app_service.course_answer_sheet(c,s)
    assert failure.value.code=="SUBMISSION_BRANCH_CONFLICT"
    resolve(app_service.learning,parent.id,ids[0],"用户确认选择第一份，第二份保留历史")
    assert app_service.course_answer_sheet(c,s)["answers"][0]["submission"]["id"]==ids[0]
    assert len(app_service.submission_detail(parent.id)["children"])==2


def test_explicit_review_round_keeps_old_evidence(app_service,synthetic):
    c,s,e=synthetic
    original=app_service.submit_answer(e,"passed original",idempotency_key="review-original")
    app_service.write_review(original.id,"passed",decision="PASSED")
    new=app_service.open_course_study(c,"explicit-review",review_round=True)
    assert new["study"]["id"]!=s
    assert new["study"]["content_hash"]==app_service.course_study_detail(s)["study"]["content_hash"]
    assert app_service.submission_detail(original.id)["answer_text"]=="passed original"
    assert app_service.course_answer_sheet(c,new["study"]["id"])["answers"][0]["action"]=="FIRST"


def test_package_replay_after_course_update_does_not_duplicate(app_service,synthetic,tmp_path):
    from studyflow.modules.courses.revisions import preview,apply
    c,s,e=synthetic
    original=tmp_path/"course.json"
    modified=package();modified["course"]["title"]="New published name"
    path=tmp_path/"changed.json";path.write_text(json.dumps(modified),encoding="utf-8")
    check=preview(app_service.courses,c,path,1)
    apply(app_service.courses,c,path,1,check["preview_hash"],"update-preserve-id")
    replay=app_service.import_course_package(original)
    assert replay["course_id"]==c and replay["created"] is False
    assert len(app_service.list_courses())==1


def test_new_method_schema_reports_field_path(app_service,synthetic):
    from studyflow.engine import StudyFlowEngine
    engine=StudyFlowEngine(service=app_service)
    try:
        result=engine.handle({"id":1,"method":"plan.edit","params":{"unknown":"value"}})
        assert result["error"]["code"]=="INVALID_ARGUMENT"
        assert "plan_line_id" in result["error"]["message"]
        schemas=engine.handle({"id":2,"method":"system.schema","params":{}})["data"]
        assert "course.update.apply" in schemas["methods"]
    finally:engine.close()


def test_hundred_courses_two_thousand_answers_queue_projection(app_service,tmp_path):
    from studyflow.modules.courses.models import Course,Lesson,Exercise
    from studyflow.modules.reviews.queue_queries import summary
    from studyflow.shared.ids import new_id
    from sqlalchemy import event
    plan=app_service.create_plan_line("Synthetic scale plan")
    with app_service.session() as db:
        for i in range(100):
            course=Course(id=new_id(),plan_line_id=plan.id,title=f"Scale {i}")
            lesson=Lesson(id=new_id(),course_id=course.id,title="Synthetic unit",markdown_path="synthetic.md")
            db.add_all([course,lesson])
            for j in range(20):
                exercise=Exercise(id=new_id(),lesson_id=lesson.id,title=f"Question {j}",prompt="Synthetic prompt")
                db.add(exercise)
                db.add(Submission(id=new_id(),exercise_id=exercise.id,answer_text="Synthetic answer",status="WAITING_REVIEW",version=1,attempt_number=1,attempt_kind="FIRST"))
    bind=app_service.session_factory.kw["bind"]
    statements=[]
    def observe(*args):statements.append(args[2])
    event.listen(bind,"before_cursor_execute",observe)
    try:queue=summary(app_service.reviews,role="agent",limit=100)
    finally:event.remove(bind,"before_cursor_execute",observe)
    assert queue["counts"]["WAITING_REVIEW"]==2000
    assert len(queue["items"])==100 and queue["next_cursor"]
    size=len(json.dumps(queue,ensure_ascii=False).encode())
    assert size<=100*1024
    assert len(statements)<=8
    artifact=tmp_path/"queue-metrics.json"
    artifact.write_text(json.dumps({"courses":100,"answers":2000,"page_items":100,"response_bytes":size,"sql_statements":len(statements)}),encoding="utf-8")


def test_engine_start_failure_releases_maintenance_lease(app_service, monkeypatch):
    from studyflow.engine import StudyFlowEngine
    from studyflow.infrastructure.leases import workspace_lease

    def fail_layout(_settings):
        raise OSError("synthetic layout failure")

    monkeypatch.setattr(type(app_service.settings), "ensure_layout", fail_layout)
    with pytest.raises(OSError, match="synthetic layout failure"):
        retained_instance = StudyFlowEngine.__new__(StudyFlowEngine)
        StudyFlowEngine.__init__(retained_instance, service=app_service)
    with workspace_lease(app_service.settings.workspace_root, exclusive=True):
        pass


def test_summary_fetches_no_answer_body_and_each_snapshot_once(app_service, tmp_path):
    from sqlalchemy import event
    from studyflow.modules.reviews.queue_queries import summary

    app_service.create_plan_line("Synthetic plan")
    payload = package(20)
    path = tmp_path / "projection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    imported = app_service.import_course_package(path)
    study = app_service.open_course_study(imported["course_id"], "projection-open")
    exercises = study["lessons"][0]["exercises"]
    app_service.write_course_answers(imported["course_id"], [
        {"exercise_id": exercise["id"], "answer_text": "Synthetic large answer " * 200}
        for exercise in exercises
    ], "SUBMIT", "projection-submit", study_session_id=study["study"]["id"])
    bind = app_service.session_factory.kw["bind"]
    statements = []
    def observe(*args):
        statements.append(args[2])
    event.listen(bind, "before_cursor_execute", observe)
    try:
        result = summary(app_service.reviews, role="agent", limit=20)
    finally:
        event.remove(bind, "before_cursor_execute", observe)
    assert len(result["items"]) == 20
    assert all("submissions.answer_text" not in sql for sql in statements)
    snapshot_reads = [sql for sql in statements if "snapshot_json" in sql]
    assert len(snapshot_reads) == 1
    assert "JOIN course_study_sessions" not in snapshot_reads[0]
    assert len(statements) <= 8

from __future__ import annotations

import pytest
from sqlalchemy import select
from studyflow.domain import DomainError
from studyflow.models import Course, Exercise, Lesson
from studyflow.services import new_id
from studyflow.engine import StudyFlowEngine


@pytest.fixture
def study_course(app_service):
    plan = app_service.create_plan_line("合成学习计划")
    ids = []
    lessons = []
    with app_service.session() as db:
        course = Course(id=new_id(), plan_line_id=plan.id, title="连续学习测试")
        db.add(course)
        for n in (1, 2):
            path = f"content/unit-{n}.md"
            file = app_service.settings.workspace_root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f"# 知识点{n}\n\n冻结前正文{n}", encoding="utf-8")
            lesson = Lesson(id=new_id(), course_id=course.id, title=f"知识点{n}", position=n, markdown_path=path)
            db.add(lesson)
            exercise = Exercise(id=new_id(), lesson_id=lesson.id, title=f"练习{n}", prompt=f"原题面{n}", position=1)
            db.add(exercise)
            lessons.append(lesson.id); ids.append(exercise.id)
        db.flush()
    return course.id, lessons, ids


def submit(app, cid, ids, sid, key="submit-study"):
    return app.write_course_answers(cid, [{"exercise_id": eid, "answer_text": f"合成答案{i}"} for i,eid in enumerate(ids)],
                                    "SUBMIT", key, study_session_id=sid)


def test_study_freezes_material_and_exercises(app_service, study_course):
    cid, lessons, ids = study_course
    opened = app_service.open_course_study(cid, "open-first")
    sid = opened["study"]["id"]
    (app_service.settings.workspace_root / "content/unit-1.md").write_text("# 新版正文", encoding="utf-8")
    with app_service.session() as db:
        db.get(Exercise, ids[0]).prompt = "已更改的题面"
    resumed = app_service.open_course_study(cid, "open-again")
    assert resumed["study"]["id"] == sid
    assert resumed["study"]["source_changed"] is True
    assert "冻结前正文1" in resumed["lessons"][0]["rendered_html"]
    assert resumed["lessons"][0]["exercises"][0]["prompt"] == "原题面1"
    result = submit(app_service, cid, ids, sid)
    original = app_service.submission_detail(result["submissions"][0]["id"])
    assert original["exercise"]["prompt"] == "原题面1"
    assert "冻结前正文1" in original["study_context"]["markdown"]
    queued = app_service.agent_queue()["waiting_review"][0]
    assert queued["batch_id"] == result["batch_id"]
    assert queued["study_session_id"] == sid
    assert queued["study_context"]["exercise"]["prompt"].startswith("原题面")


def test_skip_blank_draft_and_whole_submission(app_service, study_course):
    cid, lessons, ids = study_course
    opened = app_service.open_course_study(cid, "open-skip")
    sid = opened["study"]["id"]
    draft = app_service.write_course_answers(cid, [{"exercise_id": ids[0], "answer_text": ""}], "DRAFT_SAVE", "save-empty", study_session_id=sid)
    assert draft["submissions"][0]["status"] == "DRAFT"
    app_service.save_study_progress(sid, lessons[1], 0, '{"scrollTop":12}')
    assert app_service.course_study_detail(sid)["resume_lesson_id"] == lessons[1]
    with pytest.raises(DomainError) as error:
        submit(app_service, cid, ids[1:], sid, "incomplete")
    assert error.value.code == "INCOMPLETE_COURSE_ANSWERS"
    assert app_service.course_study_detail(sid)["course"]["study_status"] == "IN_PROGRESS"


def test_partial_review_followup_and_new_version(app_service, study_course):
    cid, lessons, ids = study_course
    sid = app_service.open_course_study(cid, "open-review")["study"]["id"]
    result = submit(app_service, cid, ids, sid)
    assert app_service.course_study_detail(sid)["course"]["study_status"] == "WAITING_REVIEW"
    first, second = result["submissions"]
    app_service.write_review(first["id"], "已通过", decision="PASSED")
    assert app_service.course_study_detail(sid)["course"]["study_status"] == "PARTIAL_FEEDBACK"
    app_service.write_review(second["id"], "需要修正", decision="REVISION_REQUIRED")
    assert app_service.course_study_detail(sid)["course"]["study_status"] == "NEEDS_REVISION"
    corrected = app_service.write_course_answers(cid, [{"exercise_id":ids[1], "answer_text":"修正版", "parent_submission_id":second["id"]}],
                                                "SUBMIT", "corrected", study_session_id=sid)
    app_service.write_review(corrected["submissions"][0]["id"], "通过", decision="PASSED")
    assert app_service.course_study_detail(sid)["course"]["study_status"] == "PASSED"
    (app_service.settings.workspace_root / "content/unit-1.md").write_text("# 新版学习", encoding="utf-8")
    newer = app_service.open_course_study(cid, "open-new", new_version=True)
    assert newer["study"]["id"] != sid
    assert newer["study"]["revision"] == 2
    assert newer["course"]["study_status"] == "IN_PROGRESS"
    assert "冻结前正文1" in app_service.course_study_detail(sid)["lessons"][0]["rendered_html"]
    assert all(item["action"] == "FIRST" for item in app_service.course_answer_sheet(cid, newer["study"]["id"])["answers"])


def test_new_version_cannot_discard_in_progress(app_service, study_course):
    cid, _, _ = study_course
    app_service.open_course_study(cid, "in-progress")
    with pytest.raises(DomainError) as error:
        app_service.open_course_study(cid, "new-too-soon", new_version=True)
    assert error.value.code == "COURSE_STUDY_IN_PROGRESS"


def test_engine_exposes_study_and_progress_version_conflicts(app_service, study_course):
    cid, lessons, _ = study_course
    engine = StudyFlowEngine(service=app_service)
    opened = engine.handle({"id":1,"method":"course.study.open","params":{"course_id":cid,"idempotency_key":"engine-open"}})
    assert opened["ok"]
    sid = opened["data"]["study"]["id"]
    first = app_service.save_study_progress(sid, lessons[0], 100, "", expected_version=1)
    assert first["version"] == 2
    with pytest.raises(DomainError) as error:
        app_service.save_study_progress(sid, lessons[1], 0, "", expected_version=1)
    assert error.value.code == "VERSION_CONFLICT"


def test_reading_only_completion(app_service, study_course):
    cid, lessons, _ = study_course
    with app_service.session() as db:
        for lesson in db.scalars(select(Lesson).where(Lesson.course_id == cid)):
            for exercise in list(lesson.exercises): db.delete(exercise)
    sid = app_service.open_course_study(cid, "reading-only")["study"]["id"]
    with pytest.raises(DomainError): app_service.complete_course_reading(sid)
    for lid in lessons: app_service.save_study_progress(sid, lid, 100, "")
    result = app_service.complete_course_reading(sid)
    assert result["course"]["study_status"] == "READ_COMPLETED"


def test_added_live_exercise_does_not_change_frozen_required_set(app_service, study_course):
    cid, lessons, ids = study_course
    sid = app_service.open_course_study(cid, "open-stable-set")["study"]["id"]
    with app_service.session() as db:
        db.add(Exercise(id=new_id(), lesson_id=lessons[0], title="后来新增", prompt="新题面", position=3))
    assert len(app_service.course_answer_sheet(cid,sid)["answers"]) == 2
    assert len(submit(app_service,cid,ids,sid)["submissions"]) == 2


def test_open_replay_and_key_conflicts(app_service, study_course):
    cid, _, _ = study_course
    first=app_service.open_course_study(cid,"open-bound")
    second=app_service.open_course_study(cid,"resume-bound")
    assert second["study"]["id"] == first["study"]["id"]
    assert app_service.open_course_study(cid,"resume-bound")["study"]["id"] == first["study"]["id"]
    with pytest.raises(DomainError) as exc: app_service.open_course_study("other-course","resume-bound")
    assert exc.value.code == "IDEMPOTENCY_KEY_CONFLICT"


def test_missing_source_can_resume_frozen_learning(app_service, study_course):
    cid, _, _=study_course
    sid=app_service.open_course_study(cid,"open-missing")["study"]["id"]
    # No delete/move: point the live metadata at an unavailable source, leaving the original file intact.
    with app_service.session() as db:
        lesson=db.scalar(select(Lesson).where(Lesson.course_id==cid).order_by(Lesson.position))
        lesson.markdown_path="content/not-created.md"
    result=app_service.course_study_detail(sid)
    assert not result["study"]["source_available"]
    assert "冻结前正文1" in result["lessons"][0]["rendered_html"]


def test_cli_discovers_and_reads_frozen_study(app_service, study_course, monkeypatch):
    import json
    import studyflow.cli as cli
    from typer.testing import CliRunner
    monkeypatch.setattr(cli,"service",lambda:app_service)
    runner=CliRunner()
    result=runner.invoke(cli.app,["course","study-open","--id",study_course[0],"--idempotency-key","cli-study","--format","json"])
    assert result.exit_code==0,result.output
    sid=json.loads(result.stdout)["study"]["id"]
    read=runner.invoke(cli.app,["course","study-detail","--study-id",sid,"--format","json"])
    assert read.exit_code==0,read.output
    assert json.loads(read.stdout)["study"]["id"]==sid
    caps=runner.invoke(cli.app,["capabilities","--format","json"])
    assert caps.exit_code==0,caps.output
    assert "course_study_open" in caps.stdout


def test_waiting_review_advances_learning_not_feedback(app_service, study_course):
    from studyflow.modules.planning.repository import ensure_course_membership
    from studyflow.models import PlanLine
    cid, _, ids=study_course
    with app_service.session() as db:
        course=db.get(Course,cid); plan=db.get(PlanLine,course.plan_line_id)
        ensure_course_membership(db,plan,course)
        second=Course(id=new_id(),plan_line_id=plan.id,title="下一门未学习课程")
        db.add(second);db.flush();ensure_course_membership(db,plan,second)
        next_id=second.id
    sid=app_service.open_course_study(cid,"open-advance")["study"]["id"]
    submit(app_service,cid,ids,sid)
    assert app_service.dashboard()["current_course"].id==next_id
    assert app_service.plan_detail(plan.id)["current_course"]["id"]==next_id
    assert len(app_service.agent_queue()["waiting_review"])==2


def test_legacy_answer_is_not_claimed_to_have_old_snapshot(app_service, study_course):
    cid, _, ids=study_course
    result=app_service.write_course_answers(cid,[{"exercise_id":e,"answer_text":"历史合成答案"} for e in ids],"SUBMIT","legacy-first")
    app_service.open_course_study(cid,"capture-after-legacy")
    detail=app_service.submission_detail(result["submissions"][0]["id"])
    assert detail["study_context"] is None
    assert detail["snapshot_status"]=="LEGACY_UNVERSIONED"


def test_retest_round_closes_without_overwriting_first_attempt(app_service, study_course):
    cid, _, ids=study_course
    sid=app_service.open_course_study(cid,"retest-start")["study"]["id"]
    first=submit(app_service,cid,ids,sid)
    for row in first["submissions"]:
        app_service.write_review(row["id"],"请独立复测",decision="RETEST_REQUIRED",detail_markdown="复测题：解释一个新的失败场景。",next_action="回答新复测题，不抄原答案。")
    assert app_service.course_study_detail(sid)["course"]["study_status"]=="RETEST_REQUIRED"
    from studyflow.modules.reviews.retests import publish
    tasks={row["id"]:publish(app_service.reviews,row["id"],"独立复测","解释一个新的失败场景。","独立解释能力","rt-"+row["id"])["id"] for row in first["submissions"]}
    retry=app_service.write_course_answers(cid,[{"exercise_id":row["exercise_id"],"answer_text":"独立复测合成答案","parent_submission_id":row["id"],"retest_task_id":tasks[row["id"]]} for row in first["submissions"]],"SUBMIT","retest-submit",study_session_id=sid)
    for row in retry["submissions"]:
        assert row["attempt_kind"]=="RETEST"
        app_service.write_review(row["id"],"复测通过",decision="PASSED")
    assert app_service.course_study_detail(sid)["course"]["study_status"]=="PASSED"
    assert all(app_service.submission_detail(row["id"])["answer_text"].startswith("合成答案") for row in first["submissions"])


def test_old_round_cannot_write_into_new_study(app_service, study_course):
    cid, lessons, ids=study_course
    sid=app_service.open_course_study(cid,"old-round-open")["study"]["id"]
    first=submit(app_service,cid,ids,sid)
    for row in first["submissions"]: app_service.write_review(row["id"],"通过",decision="PASSED")
    (app_service.settings.workspace_root/'content/unit-1.md').write_text("# 全新内容",encoding="utf-8")
    new=app_service.open_course_study(cid,"new-round-open",new_version=True)
    with pytest.raises(DomainError) as exc:
        app_service.write_course_answers(cid,[{"exercise_id":ids[0],"answer_text":"旧窗口尝试修改"}],"DRAFT_SAVE","old-write",study_session_id=sid)
    assert exc.value.code=="VERSION_CONFLICT"
    assert not app_service.course_answer_sheet(cid,new["study"]["id"])["answers"][0]["draft"]


def test_single_cli_adapters_keep_same_snapshot_round(app_service, study_course):
    cid, _, ids=study_course
    sid=app_service.open_course_study(cid,"single-adapter-round")["study"]["id"]
    draft=app_service.save_submission_draft(ids[0],"单题合成草稿",idempotency_key="single-draft")
    assert draft.study_session_id==sid
    formal=app_service.submit_submission(exercise_id=ids[0],submission_id=draft.id,expected_version=draft.version,idempotency_key="single-formal")
    assert app_service.submission_detail(formal.id)["study_context"]["study_session_id"]==sid
    app_service.write_review(formal.id,"需要修正",decision="REVISION_REQUIRED")
    revised=app_service.revise_submission(formal.id,"单题合成修正",idempotency_key="single-revised")
    assert revised.study_session_id==sid
    assert app_service.course_answer_sheet(cid,sid)["answers"][0]["submission"]["id"]==revised.id

from __future__ import annotations
import json
import pytest
from studyflow.modules.learning.english.checker import check_answer, tokenize
from studyflow.modules.courses.content import validate_package
from studyflow.shared.domain import DomainError


def english_package(mode="local_exact"):
    return {"schema":"studyflow.course-package/2","package_id":"english-test","plan_line":"英语试验", "course":{"title":"表达喜好","learning_mode":"english"},"lessons":[{"id":"likes","title":"表达喜好","blocks":[{"id":"intro","type":"concept","title":"I like","body":"I like 表示我喜欢。"}],"exercises":[{"id":"tea","title":"我喜欢茶","prompt":"我喜欢茶。","english":{"target":"I like tea.","accepted_answers":[],"evaluation_mode":mode,"objective_ids":["likes"]}},{"id":"coffee","title":"我喜欢咖啡","prompt":"我喜欢咖啡。","english":{"target":"I like coffee.","objective_ids":["likes"]}}]}]}


def install(app_service,tmp_path,mode="local_exact"):
    app_service.create_plan_line("英语试验")
    p=tmp_path/"english.json";p.write_text(json.dumps(english_package(mode),ensure_ascii=False),encoding="utf-8")
    course=app_service.import_course_package(p)
    opened=app_service.open_course_study(course["course_id"],"open-en")
    return course,opened


def test_checker_whole_variants_and_differences():
    spec={"target":"I like tea.","accepted_answers":["We enjoy tea."],"case_sensitive":False}
    assert tokenize("I don't re-enter.")==["I","don't","re-enter"]
    assert check_answer(spec,"  i LIKE tea. ")["matched"]
    assert not check_answer(spec,"I enjoy tea.")["matched"]
    wrong=check_answer(spec,"I lik tea")
    assert [x["index"] for x in wrong["differences"]]==[1]
    assert not check_answer(spec,"I like tea extra")["matched"]


def test_package_v2_is_strict():
    assert validate_package(english_package())["course"]["learning_mode"]=="english"
    bad=english_package();bad["lessons"][0]["exercises"][0]["english"]["magic"]=True
    with pytest.raises(DomainError):validate_package(bad)
    bad=english_package();bad["lessons"][0]["exercises"][0]["english"]["accepted_answers"]=["Tea."]
    with pytest.raises(DomainError):validate_package(bad)


def test_frozen_training_checks_and_submit(app_service,tmp_path):
    course,opened=install(app_service,tmp_path)
    sid=opened["study"]["id"]
    view=app_service.english.get(sid)
    assert len(view["items"])==2
    assert "target" not in view["items"][0]
    ex=view["items"][0]["exercise_id"]
    save=app_service.english.save(sid,ex,"I lik tea",0,"save-1")
    wrong=app_service.english.check(sid,ex,save["answer_version"],"check-1")
    assert not wrong["matched"] and wrong["differences"][0]["index"]==1
    assert app_service.english.check(sid,ex,save["answer_version"],"check-1")==wrong
    plan_id=course["plan_id"]
    stats=app_service.mistakes.summary(plan_line_id=plan_id,domain="english")
    assert stats["failed_attempts"]==1 and stats["review_total"]==0
    fix=app_service.english.save(sid,ex,"I like tea.",save["answer_version"],"fix-1")
    passed=app_service.english.check(sid,ex,fix["answer_version"],"check-2")
    assert passed["matched"]
    with pytest.raises(DomainError):app_service.english.submit(sid,"submit-incomplete")
    other=view["items"][1]["exercise_id"]
    saved=app_service.english.save(sid,other,"I like coffee",0,"save-2")
    app_service.english.check(sid,other,saved["answer_version"],"check-3")
    result=app_service.english.submit(sid,"submit-all")
    assert result["completed"] and result["waiting_review"]==0
    assert app_service.course_study_detail(sid)["course"]["study_status"]=="PASSED"


def test_cas_and_edit_invalidates_check(app_service,tmp_path):
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    ex=app_service.english.get(sid)["items"][0]["exercise_id"]
    a=app_service.english.save(sid,ex,"I like tea",0,"save")
    app_service.english.check(sid,ex,a["answer_version"],"check")
    with pytest.raises(DomainError):app_service.english.save(sid,ex,"overwrite",0,"stale")
    b=app_service.english.save(sid,ex,"changed",a["answer_version"],"edit")
    assert b["answer_version"]>a["answer_version"]
    assert not app_service.english.get(sid)["items"][0]["matched"]



def finish(app_service,opened):
    sid=opened["study"]["id"]
    for n,ex in enumerate(app_service.english.get(sid)["items"]):
        answer="I like tea" if n==0 else "I like coffee"
        saved=app_service.english.save(sid,ex["exercise_id"],answer,ex["answer_version"],f"finish-{n}")
        app_service.english.check(sid,ex["exercise_id"],saved["answer_version"],f"finish-check-{n}")
    return app_service.english.submit(sid,"finish-submit")


def test_scope_review_and_retest_preserve_evidence(app_service,tmp_path):
    course,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    item=app_service.english.get(sid)["items"][0]
    a=app_service.english.save(sid,item["exercise_id"],"I lik tea",0,"first")
    app_service.english.check(sid,item["exercise_id"],a["answer_version"],"wrong")
    finish(app_service,opened)
    scope={"plan_line_id":course["plan_id"],"domain":"english"}
    aggregate=app_service.mistakes.list(**scope)["items"][0]
    app_service.mistakes.select_review(aggregate["id"],aggregate["version"],"select-review",**scope)
    aggregate=app_service.mistakes.list(**scope)["items"][0]
    task=app_service.mistakes.retest_request(aggregate["id"],aggregate["version"],"retest",**scope)
    result=app_service.english.retest_check(task["task_id"],"I like tea","retest-answer")
    assert result["matched"]
    assert app_service.english.retest_check(task["task_id"],"I like tea","retest-answer")==result
    assert app_service.mistakes.summary(**scope)["review_total"]==0
    original=app_service.mistakes.context(aggregate["id"],**scope)
    assert original["evidence"][0]["answer_text"]=="I lik tea"
    other=app_service.create_plan_line("别的计划")
    with pytest.raises(DomainError):app_service.mistakes.context(aggregate["id"],plan_line_id=other.id,domain="english")


def test_agent_accepts_alternative_without_marking_it_language_error(app_service,tmp_path):
    course,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    ex=app_service.english.get(sid)["items"][0]
    saved=app_service.english.save(sid,ex["exercise_id"],"I enjoy tea",0,"save-alt")
    app_service.english.check(sid,ex["exercise_id"],saved["answer_version"],"check-alt")
    request=app_service.english.request_review(sid,ex["exercise_id"],saved["answer_version"],"request-alt")
    app_service.write_review(request["submission_id"],"合理等价表达",decision="PASSED",idempotency_key="accept-alt")
    stats=app_service.mistakes.summary(plan_line_id=course["plan_id"],domain="english")
    assert stats["failed_attempts"]==1 and stats["valid_error_evidence"]==0


def test_reveal_and_offline_dictionary_are_nonblocking(app_service,tmp_path):
    from studyflow.modules.audio.dictionary.provider import DictionaryProvider
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    ex=app_service.english.get(sid)["items"][0]
    assert app_service.audio.lookup(sid,ex["exercise_id"])["whole_sentence"]
    app_service.english.reveal(sid,ex["exercise_id"],"reveal")
    assert app_service.english.get(sid)["items"][0]["assisted"]
    def unavailable(url):raise OSError("offline")
    app_service.audio.provider=DictionaryProvider(fetch=unavailable)
    info=app_service.audio.lookup(sid,ex["exercise_id"],word_index=1)
    assert info["metadata_status"] in {"loading","unavailable"} and not info["definition_available"]
    assert "lik" not in info["pronunciation_url"].split("audio=")[0]


def test_engine_contract_rejects_unknown_and_false_score(app_service,tmp_path):
    from studyflow.engine import StudyFlowEngine
    course,opened=install(app_service,tmp_path)
    engine=StudyFlowEngine(service=app_service)
    caps=engine.handle({"id":1,"method":"system.capabilities","params":{}})
    assert caps["ok"]
    schema=engine.handle({"id":2,"method":"system.schema","params":{"method":"course.english.check"}})
    assert schema["ok"]
    invalid=engine.handle({"id":3,"method":"course.english.check","params":{"study_session_id":opened["study"]["id"],"exercise_id":"unknown","expected_version":1,"idempotency_key":"test","matched":True}})
    assert not invalid["ok"] and invalid["error"]["code"]=="INVALID_ARGUMENT"
    empty=engine.handle({"id":4,"method":"mistakes.summary","params":{}})
    assert not empty["ok"] and empty["error"]["code"]=="SCOPE_REQUIRED"


def test_plain_error_and_english_errors_use_different_books(app_service,tmp_path):
    from studyflow.modules.courses.models import Course,Lesson,Exercise
    from studyflow.shared.ids import new_id
    from studyflow.modules.planning.repository import ensure_course_membership
    plan=app_service.create_plan_line("普通试验")
    path=tmp_path/"plain.md";path.write_text("# 普通内容",encoding="utf-8")
    with app_service.session() as db:
        course=Course(id=new_id(),plan_line_id=plan.id,title="普通课")
        db.add(course);db.flush();ensure_course_membership(db,plan,course)
        lesson=Lesson(id=new_id(),course_id=course.id,title="普通知识",markdown_path="plain.md");db.add(lesson);db.flush()
        ex=Exercise(id=new_id(),lesson_id=lesson.id,title="解释",prompt="解释概念");db.add(ex);db.flush();cid=course.id;eid=ex.id
    opened=app_service.open_course_study(cid,"plain-open")
    response=app_service.write_course_answers(cid,[{"exercise_id":eid,"answer_text":"合成错误"}],"SUBMIT","plain-submit",study_session_id=opened["study"]["id"])
    queue=app_service.agent_queue()["waiting_review"]
    app_service.write_review(queue[0]["id"],"请修正",decision="REVISION_REQUIRED",idempotency_key="plain-review")
    assert app_service.mistakes.summary(plan_line_id=plan.id,domain="general")["entry_total"]==1
    assert app_service.mistakes.summary(plan_line_id=plan.id,domain="english")["entry_total"]==0


def make_retest(app_service, tmp_path):
    course, opened = install(app_service, tmp_path)
    sid = opened["study"]["id"]
    ex = app_service.english.get(sid)["items"][0]
    saved = app_service.english.save(sid, ex["exercise_id"], "I lik tea", 0, "wrong-save")
    app_service.english.check(sid, ex["exercise_id"], saved["answer_version"], "wrong-check")
    finish(app_service, opened)
    scope = {"plan_line_id": course["plan_id"], "domain": "english"}
    entry = app_service.mistakes.list(**scope)["items"][0]
    app_service.mistakes.select_review(entry["id"], entry["version"], "select", **scope)
    entry = app_service.mistakes.list(**scope)["items"][0]
    published = app_service.mistakes.retest_request(entry["id"], entry["version"], "publish", **scope)
    return scope, entry, published


def test_retest_draft_cas_resume_and_stable_publish_receipt(app_service, tmp_path):
    scope, entry, published = make_retest(app_service, tmp_path)
    tid = published["task_id"]
    assert app_service.english.retest_get(tid)["answer_version"] == 0
    saved = app_service.english.retest_save(tid, "I like", 0, "retest-save")
    assert app_service.english.retest_save(tid, "I like", 0, "retest-save") == saved
    restored = app_service.english.retest_get(tid)
    assert restored["answer_text"] == "I like" and restored["status"] == "IN_PROGRESS"
    with pytest.raises(DomainError) as exc:
        app_service.english.retest_save(tid, "overwrite", 0, "stale-retest")
    assert exc.value.code == "VERSION_CONFLICT"
    result = app_service.english.retest_check(tid, "I like tea", "retest-done", saved["answer_version"])
    assert result["matched"]
    assert app_service.english.retest_get(tid)["result"]["matched"]
    assert app_service.mistakes.retest_request(entry["id"], entry["version"], "publish", **scope) == published
    with pytest.raises(DomainError) as exc:
        app_service.mistakes.retest_request(entry["id"], entry["version"]+1, "publish", **scope)
    assert exc.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    with pytest.raises(DomainError):
        app_service.english.retest_save(tid, "changed", result["answer_version"], "after-done")


def test_pagination_scope_and_evidence_time_counts(app_service, tmp_path):
    from datetime import datetime
    from sqlalchemy import select
    from studyflow.modules.mistakes.english.models import EnglishErrorEvidence, EnglishErrorAggregate
    course, opened = install(app_service, tmp_path)
    sid = opened["study"]["id"]
    items = app_service.english.get(sid)["items"]
    for i, item in enumerate(items):
        saved = app_service.english.save(sid, item["exercise_id"], "I lik tea", 0, f"save-{i}")
        app_service.english.check(sid, item["exercise_id"], saved["answer_version"], f"check-{i}")
    scope = {"plan_line_id": course["plan_id"], "domain": "english"}
    assert app_service.mistakes.summary(**scope)["failed_rounds"] == 1
    page = app_service.mistakes.list(limit=1, **scope)
    assert page["next_cursor"] and len(app_service.mistakes.list(limit=1, cursor=page["next_cursor"], **scope)["items"]) == 1
    with pytest.raises(DomainError) as exc:
        app_service.mistakes.list(limit=1, cursor=page["next_cursor"], course_id="another-course", **scope)
    assert exc.value.code == "INVALID_CURSOR"
    eid = items[0]["exercise_id"]
    version = app_service.english.get(sid)["items"][0]["answer_version"]
    again = app_service.english.check(sid, eid, version, "again")
    with app_service.session() as db:
        for aggregate in db.scalars(select(EnglishErrorAggregate)):
            aggregate.created_at = datetime(2020, 1, 1)
        evidences = list(db.scalars(select(EnglishErrorEvidence).order_by(EnglishErrorEvidence.created_at, EnglishErrorEvidence.id)))
        for evidence in evidences: evidence.created_at = datetime(2020, 1, 1)
        evidence = db.scalar(select(EnglishErrorEvidence).where(EnglishErrorEvidence.attempt_id == again["attempt_id"]))
        evidence.created_at = datetime(2026, 10, 11)
    scoped = {**scope, "since": "2026-10-10T00:00:00", "until": "2026-10-12T00:00:00"}
    assert app_service.mistakes.summary(**scoped)["failed_attempts"] == 1
    row = app_service.mistakes.list(**scoped)["items"][0]
    assert row["failed_attempts"] == 1 and row["lifetime_failed_attempts"] == 2
    context = app_service.mistakes.context(row["id"], **scoped)
    assert len(context["evidence"]) == 1


def test_plan_membership_freezes_and_rejects_invalid_resume(app_service, tmp_path):
    from studyflow.modules.planning.repository import ensure_course_membership
    from studyflow.modules.courses.models import Course
    course, opened = install(app_service, tmp_path)
    second = app_service.create_plan_line("第二计划")
    with app_service.session() as db:
        ensure_course_membership(db, db.get(type(second), second.id), db.get(Course, course["course_id"]))
    same = app_service.open_course_study(course["course_id"], "other-entry", plan_line_id=second.id)
    assert same["course"]["plan_line_id"] == course["plan_id"] and same["scope_notice"]
    unrelated = app_service.create_plan_line("无关计划")
    with pytest.raises(DomainError) as exc:
        app_service.open_course_study(course["course_id"], "invalid-entry", plan_line_id=unrelated.id)
    assert exc.value.code == "SCOPE_MISMATCH"
    finish(app_service, opened)
    next_round = app_service.open_course_study(course["course_id"], "second-round", review_round=True, plan_line_id=second.id)
    assert next_round["course"]["plan_line_id"] == second.id


def test_reveal_without_prior_draft_returns_current_cas(app_service, tmp_path):
    _, opened = install(app_service, tmp_path)
    sid = opened["study"]["id"]
    eid = app_service.english.get(sid)["items"][0]["exercise_id"]
    revealed = app_service.english.reveal(sid, eid, "reveal-empty")
    saved = app_service.english.save(sid, eid, "I like tea", revealed["answer_version"], "after-reveal")
    assert saved["answer_version"] > revealed["answer_version"]


def test_revision_resets_training_and_seals_old_round(app_service, tmp_path):
    from studyflow.modules.courses.revisions import preview, apply
    course, opened = install(app_service, tmp_path)
    sid = opened["study"]["id"]
    updated = english_package()
    updated["lessons"][0]["exercises"][0]["english"]["target"] = "I enjoy tea."
    path = tmp_path / "revised.json"
    path.write_text(json.dumps(updated), encoding="utf-8")
    proposed = preview(app_service.courses, course["course_id"], path, 1)
    applied = apply(app_service.courses, course["course_id"], path, 1, proposed["preview_hash"], "revise")
    assert applied["learning_state_reset"] is True
    assert app_service.english.get(sid)["course"]["source_changed"]
    eid = app_service.english.get(sid)["items"][0]["exercise_id"]
    with pytest.raises(DomainError) as late:
        app_service.english.save(sid, eid, "I like tea", 0, "old-save")
    assert late.value.code == "STUDY_ROUND_SUPERSEDED"
    fresh = app_service.open_course_study(course["course_id"], "after-reset-open")
    fresh_sid = fresh["study"]["id"]
    assert fresh_sid != sid and fresh["study"]["is_current"] is True
    saved = app_service.english.save(fresh_sid, eid, "I like tea", 0, "new-save")
    assert not app_service.english.check(fresh_sid, eid, saved["answer_version"], "new-check")["matched"]
    assert app_service.course_study_detail(sid)["study"]["is_current"] is False


def test_archive_is_logical_idempotent_and_protects_active_retests(app_service, tmp_path):
    scope, entry, published = make_retest(app_service, tmp_path)
    with pytest.raises(DomainError) as exc:
        app_service.mistakes.archive_preview(**scope)
    assert exc.value.code == "ACTIVE_TASK_PROTECTED"
    app_service.english.retest_check(published["task_id"], "I like tea", "pass")
    preview = app_service.mistakes.archive_preview(**scope)
    result = app_service.mistakes.archive_apply(preview["preview_hash"], "archive", **scope)
    assert app_service.mistakes.archive_apply(preview["preview_hash"], "archive", **scope) == result
    assert app_service.mistakes.summary(**scope)["entry_total"] == 0
    archived = {**scope, "archived": True}
    assert app_service.mistakes.summary(**archived)["entry_total"] == 1
    assert app_service.mistakes.context(entry["id"], **archived)["evidence"][0]["answer_text"] == "I lik tea"


def test_english_purge_obeys_enforced_foreign_keys_and_preserves_other_plans(app_service, tmp_path):
    from sqlalchemy import text, event
    engine = app_service.session_factory.kw["bind"]
    def enforce(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    event.listen(engine, "connect", enforce)
    with engine.connect() as connection: connection.execute(text("PRAGMA foreign_keys=ON"))
    scope, entry, published = make_retest(app_service, tmp_path)
    app_service.english.retest_save(published["task_id"], "I like", 0, "draft")
    app_service.english.retest_check(published["task_id"], "I like tea", "passed", 1)
    preserved = app_service.create_plan_line("保留计划")
    assert app_service.preview_course_purge([entry["course_id"]])["course_ids"] == [entry["course_id"]]
    app_service.purge_courses(confirm=True, course_ids=[entry["course_id"]])
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("select count(*) from english_error_evidence")).scalar() == 0
        assert connection.execute(text("select count(*) from plan_lines where id=:id"), {"id": preserved.id}).scalar() == 1


def test_v6_complete_variants_and_sentence_parts(app_service,tmp_path):
    p=english_package();p["schema"]="studyflow.course-package/6"
    spec=p["lessons"][0]["exercises"][0]["english"]
    spec.update(target="He does not have a plan.",accepted_answers=["He doesn't have a plan."],sentence_parts=[
        {"role":"subject","start":0,"end":1,"words":[{"gloss":"他","pos":"代词"}]},
        {"role":"predicate","start":1,"end":4,"words":[{}, {}, {}]},
        {"role":"object","start":4,"end":6,"words":[{}, {"gloss":"计划","pos":"名词"}]}])
    assert validate_package(p)
    assert check_answer(spec,"He doesn't have a plan")["matched"]
    assert not check_answer(spec,"He doesn't not have a plan")["matched"]
    spec["sentence_parts"][1]["start"]=2
    with pytest.raises(DomainError):validate_package(p)
    spec["sentence_parts"][1]["start"]=1;spec["evaluation_mode"]="agent"
    with pytest.raises(DomainError):validate_package(p)


def test_legacy_open_item_has_local_exact_result(app_service,tmp_path):
    _,opened=install(app_service,tmp_path,"agent");sid=opened["study"]["id"]
    ex=app_service.english.get(sid)["items"][0]["exercise_id"]
    saved=app_service.english.save(sid,ex,"I like tea",0,"legacy-save")
    result=app_service.english.check(sid,ex,saved["answer_version"],"legacy-check")
    assert result["matched"] is True and not result.get("requires_agent")


def test_audio_can_read_frozen_target_before_answer_without_revealing_text(app_service,tmp_path):
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    ex=app_service.english.get(sid)["items"][0]["exercise_id"]
    voice=app_service.audio.lookup(sid,ex)
    assert voice["whole_sentence"] and voice["target"]=="I like tea."
    assert not app_service.english.get(sid)["items"][0]["assisted"]
    with pytest.raises(DomainError):app_service.english.answer(sid,ex)


def test_consecutive_errors_replay_and_correct_then_submit(app_service,tmp_path):
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    ex=app_service.english.get(sid)["items"][0]["exercise_id"]
    saved=app_service.english.save(sid,ex,"I lik tea",0,"wrong-save")
    assert app_service.english.check(sid,ex,saved["answer_version"],"wrong-check1")["error_count"]==1
    assert app_service.english.check(sid,ex,saved["answer_version"],"wrong-check2")["error_count"]==2
    assert app_service.english.check(sid,ex,saved["answer_version"],"wrong-check2")["error_count"]==2
    saved=app_service.english.save(sid,ex,"I like tea",saved["answer_version"],"correct-save")
    assert app_service.english.check(sid,ex,saved["answer_version"],"correct-check")["error_count"]==0
    assert app_service.english.get(sid)["items"][0]["error_count"]==0
    with pytest.raises(DomainError,match="未完成"):app_service.english.submit(sid,"has-gap")


def test_legacy_queued_last_answer_does_not_block_whole_training_or_become_a_fabricated_pass(app_service, tmp_path):
    _, opened = install(app_service, tmp_path, mode="agent")
    sid = opened["study"]["id"]
    view = app_service.english.get(sid)
    queued, exact = [item["exercise_id"] for item in view["items"]]
    saved = app_service.english.save(sid, queued, "My own sentence", 0, "legacy-save")
    review = app_service.english.request_review(sid, queued, saved["answer_version"], "legacy-queue")
    saved_exact = app_service.english.save(sid, exact, "I like coffee", 0, "exact-save")
    app_service.english.check(sid, exact, saved_exact["answer_version"], "exact-check")
    before = app_service.english.get(sid)
    versions = {row["exercise_id"]: row["answer_version"] for row in before["items"]}
    result = app_service.english.submit(sid, "finish-legacy", versions)
    assert result["completed"] is True
    assert result["waiting_review"] == 1
    after = app_service.english.get(sid)
    pending = next(row for row in after["items"] if row["exercise_id"] == queued)
    assert pending["status"] == "WAITING_REVIEW"
    assert pending["matched"] is False
    assert pending["answer_text"] == "My own sentence"
    assert pending["answer_version"] == review["answer_version"]
    assert pending["submission_id"] == review["submission_id"]
    assert after["completed"] is True
    assert app_service.english.submit(sid, "finish-legacy", versions) == result


@pytest.mark.parametrize("opening", [{"new_version": True}, {"review_round": True}])
def test_submitted_legacy_english_round_can_open_updated_material_without_resolving_pending_history(app_service, tmp_path, opening):
    from studyflow.modules.courses.revisions import preview, apply
    course, opened = install(app_service, tmp_path, mode="agent")
    sid = opened["study"]["id"]
    queued, exact = [row["exercise_id"] for row in app_service.english.get(sid)["items"]]
    a = app_service.english.save(sid, queued, "My own sentence", 0, "queue-answer")
    pending = app_service.english.request_review(sid, queued, a["answer_version"], "queue-answer-review")
    b = app_service.english.save(sid, exact, "I like coffee", 0, "exact-answer")
    app_service.english.check(sid, exact, b["answer_version"], "exact-answer-check")
    app_service.english.submit(sid, "submit-before-update")
    old = app_service.english.get(sid)
    assert old["completed"] is True
    assert app_service.course_study_detail(sid)["course"]["study_status"] == "PARTIAL_FEEDBACK"
    updated = english_package()
    updated["schema"] = "studyflow.course-package/6"
    updated["lessons"][0]["exercises"][0]["english"]["target"] = "I enjoy tea."
    path = tmp_path / "updated-local.json"
    path.write_text(json.dumps(updated, ensure_ascii=False), encoding="utf-8")
    proposal = preview(app_service.courses, course["course_id"], path, 1)
    apply(app_service.courses, course["course_id"], path, 1, proposal["preview_hash"], "publish-new-local")
    overview = app_service.course_detail(course["course_id"])["course"]
    assert overview["can_start_new_round"] is True
    assert overview["source_changed"] is True and overview["study_content_revision"] == 1
    new = app_service.open_course_study(course["course_id"], "explicit-new", **opening)
    assert new["study"]["id"] != sid
    assert new["course"]["content_revision"] == 2
    assert app_service.open_course_study(course["course_id"], "explicit-new", **opening)["study"]["id"] == new["study"]["id"]
    fresh = app_service.english.get(new["study"]["id"])
    assert fresh["completed"] is False
    assert all(row["answer_text"] == "" and row["answer_version"] == 0 for row in fresh["items"])
    preserved = app_service.english.get(sid)["items"][0]
    assert preserved["status"] == "WAITING_REVIEW"
    assert preserved["matched"] is False
    assert preserved["answer_text"] == old["items"][0]["answer_text"]
    assert preserved["answer_version"] == pending["answer_version"]
    assert preserved["submission_id"] == pending["submission_id"]
    assert app_service.submission_detail(pending["submission_id"])["status"] == "WAITING_REVIEW"
    saved = app_service.english.save(fresh["study_session_id"], queued, "I enjoy tea", 0, "new-answer")
    assert app_service.english.check(fresh["study_session_id"], queued, saved["answer_version"], "new-answer-check")["matched"] is True


@pytest.mark.parametrize("opening", [{"new_version": True}, {"review_round": True}])
def test_unsubmitted_english_round_with_queued_answer_cannot_be_discarded_by_new_round(app_service, tmp_path, opening):
    course, opened = install(app_service, tmp_path, mode="agent")
    sid = opened["study"]["id"]
    queued = app_service.english.get(sid)["items"][0]["exercise_id"]
    saved = app_service.english.save(sid, queued, "My own sentence", 0, "unsubmitted-save")
    app_service.english.request_review(sid, queued, saved["answer_version"], "unsubmitted-review")
    with pytest.raises(DomainError) as exc:
        app_service.open_course_study(course["course_id"], "do-not-discard", **opening)
    assert exc.value.code == "COURSE_STUDY_IN_PROGRESS"
    assert app_service.english.get(sid)["completed"] is False
    assert app_service.course_detail(course["course_id"])["course"]["study_session_id"] == sid


def test_completed_english_with_revision_required_still_cannot_start_another_round(app_service, tmp_path):
    course, opened = install(app_service, tmp_path, mode="agent")
    sid = opened["study"]["id"]
    first, second = [row["exercise_id"] for row in app_service.english.get(sid)["items"]]
    a = app_service.english.save(sid, first, "My own sentence", 0, "needs-fix-save")
    pending = app_service.english.request_review(sid, first, a["answer_version"], "needs-fix-review")
    b = app_service.english.save(sid, second, "I like coffee", 0, "needs-fix-exact")
    app_service.english.check(sid, second, b["answer_version"], "needs-fix-check")
    app_service.english.submit(sid, "finish-then-feedback")
    app_service.write_review(pending["submission_id"], "请修正", decision="REVISION_REQUIRED", idempotency_key="needs-fix-feedback")
    assert app_service.english.get(sid)["completed"] is True
    assert app_service.course_detail(course["course_id"])["course"]["can_start_new_round"] is False
    with pytest.raises(DomainError) as exc:
        app_service.open_course_study(course["course_id"], "blocked-feedback", review_round=True)
    assert exc.value.code == "COURSE_STUDY_IN_PROGRESS"

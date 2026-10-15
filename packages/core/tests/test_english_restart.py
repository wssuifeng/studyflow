import json
import pytest
from sqlalchemy import select
from studyflow.domain import DomainError
from studyflow.modules.learning.restart import preview, restart
from studyflow.modules.learning.models import CourseStudySession, CourseWriteReceipt
from studyflow.modules.learning.english.models import EnglishStudyState
from studyflow.shared.ids import new_id
from test_english_specialty import install


def request(info, key="restart-empty-english"):
    return dict(study_session_id=info["study_session_id"], expected_version=info["expected_version"], expected_content_hash=info["expected_content_hash"], expected_training_version=info["expected_training_version"], idempotency_key=key)


def test_empty_english_navigation_restart_preserves_history_notes_and_replay(app_service,tmp_path):
    course,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    before=opened["study"]["content_hash"]
    view=app_service.english.get(sid)
    app_service.english.navigate(sid,1,view["state_version"],"browse-only")
    app_service.save_study_note(sid,opened["lessons"][0]["id"],"keep note",0,"note-empty-en")
    info=preview(app_service.learning,sid)
    assert info["can_restart"],info
    args=request(info);fresh=restart(app_service.learning,**args)
    assert fresh["study"]["id"]!=sid
    assert restart(app_service.learning,**args)["study"]["id"]==fresh["study"]["id"]
    old=app_service.course_study_detail(sid)
    assert old["course"]["study_status"]=="ABANDONED"
    assert old["study"]["content_hash"]==before
    assert app_service.study_notes(sid)["notes"][0]["text"]=="keep note"
    assert app_service.english.get(fresh["study"]["id"])["position"]==0


@pytest.mark.parametrize("evidence",["empty-save","hint","completed","unknown-write"])
def test_restart_preserves_any_english_evidence(app_service,tmp_path,evidence):
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    info=preview(app_service.learning,sid);assert info["can_restart"]
    ex=app_service.english.get(sid)["items"][0]["exercise_id"]
    if evidence=="empty-save":app_service.english.save(sid,ex,"",0,"empty-evidence")
    elif evidence=="hint":app_service.english.reveal(sid,ex,"hint-evidence")
    else:
        with app_service.session() as db:
            if evidence=="completed":db.add(EnglishStudyState(study_session_id=sid,version=1,position=0,completed=True))
            else:db.add(CourseWriteReceipt(id=new_id(),idempotency_key="unknown",course_id=opened["course"]["id"],study_session_id=sid,operation="FUTURE_WRITE",payload_hash="a"*64,result_json="{}"))
    assert not preview(app_service.learning,sid)["can_restart"]
    with pytest.raises(DomainError) as caught:restart(app_service.learning,**request(info))
    assert caught.value.code=="STUDY_RESTART_BLOCKED"


def test_restart_rechecks_training_navigation_version(app_service,tmp_path):
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    info=preview(app_service.learning,sid)
    app_service.english.navigate(sid,1,app_service.english.get(sid)["state_version"],"move-after-preview")
    with pytest.raises(DomainError) as caught:restart(app_service.learning,**request(info))
    assert caught.value.code=="VERSION_CONFLICT"
    assert app_service.course_study_detail(sid)["study"]["is_current"]


@pytest.mark.parametrize("evidence",["reference","read-complete","legacy-unknown"])
def test_restart_keeps_auxiliary_or_unknown_learning_evidence(app_service,tmp_path,evidence):
    from studyflow.modules.learning.models import CourseReferenceView
    _,opened=install(app_service,tmp_path);sid=opened["study"]["id"]
    with app_service.session() as db:
        row=db.get(CourseStudySession,sid)
        if evidence=="reference":db.add(CourseReferenceView(study_session_id=sid,exercise_id=opened["lessons"][0]["exercises"][0]["id"],reference_hash="a"*64))
        elif evidence=="read-complete":row.reading_completed=True
        else:row.hint_tracking_enabled=False
    assert not preview(app_service.learning,sid)["can_restart"]

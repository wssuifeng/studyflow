import copy
import json
import pytest
from pathlib import Path
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.content import validate_package, fallback_markdown
from studyflow.modules.learning.models import CourseStudySession
from test_course_packages import sample, package_file
from test_course_study import study_course


def detailed_package():
    data=sample();data['schema']='studyflow.course-package/3'
    data['lessons'][0]['blocks'].insert(1,{'id':'detail','type':'details','title':'为什么','summary':'先记住结论。','body':'### 深入推导\n完整的 **解释**。<script>bad()</script>'})
    return data


def test_details_contract_fallback_render_and_frozen_version(app_service,tmp_path):
    data=detailed_package();assert validate_package(data)==data
    fallback=fallback_markdown(data['lessons'][0]);assert '先记住结论' in fallback and '深入推导' in fallback
    app_service.create_plan_line('Testing');imported=app_service.import_course_package(package_file(tmp_path,data))
    opened=app_service.open_course_study(imported['course_id'],'details-open')
    block=opened['lessons'][0]['content_blocks'][1]
    assert block['summary_html'].startswith('<p>') and '<script>' not in block['body_html']
    file=tmp_path/imported['paths'][0];file.write_text(file.read_text(encoding='utf-8').replace('完整的','修改后的'),encoding='utf-8')
    frozen=app_service.course_study_detail(opened['study']['id'])
    assert frozen['study']['source_changed'] and frozen['lessons'][0]['content_blocks'][1]==block


@pytest.mark.parametrize('change',['legacy','empty','nested','too-long'])
def test_details_reject_unsupported_or_invalid_fields(change):
    data=detailed_package();block=data['lessons'][0]['blocks'][1]
    if change=='legacy':data['schema']='studyflow.course-package/1'
    if change=='empty':block['summary']=' '
    if change=='nested':block['blocks']=[]
    if change=='too-long':block['summary']='x'*3001
    with pytest.raises(DomainError):validate_package(data)


def test_restart_preserves_notes_history_and_replay(app_service,study_course):
    from studyflow.modules.learning.restart import preview, restart
    cid,lessons,_=study_course;opened=app_service.open_course_study(cid,'restart-open');sid=opened['study']['id']
    app_service.save_study_note(sid,lessons[0],'保留学习笔记',0,'note-before-restart')
    app_service.save_study_progress(sid,lessons[0],2,'old-anchor')
    from studyflow.modules.learning.restart import latest_content
    with app_service.session(read_only=True) as db:latest_content(app_service.learning,db.get(CourseStudySession,sid))
    info=preview(app_service.learning,sid);assert info['can_restart']
    args={'study_session_id':sid,'expected_version':info['expected_version'],'expected_content_hash':info['expected_content_hash'],'idempotency_key':'restart-once'}
    fresh=restart(app_service.learning,**args);assert fresh['study']['id']!=sid
    assert fresh['course']['reading_percent']==0
    assert restart(app_service.learning,**args)['study']['id']==fresh['study']['id']
    old=app_service.course_study_detail(sid);assert old['course']['study_status']=='ABANDONED' and not old['study']['is_current']
    assert app_service.study_notes(sid)['notes'][0]['text']=='保留学习笔记'
    with pytest.raises(DomainError):app_service.save_study_progress(sid,lessons[0],4,'late')
    with pytest.raises(DomainError):app_service.save_study_note(sid,lessons[0],'late note',1,'late-note')
    with app_service.session() as db:assert len(db.scalars(select(CourseStudySession)).all())==2


def test_restart_rechecks_drafts_after_preview(app_service,study_course):
    from studyflow.modules.learning.restart import preview, restart
    cid,_,ids=study_course;sid=app_service.open_course_study(cid,'draft-check')['study']['id']
    info=preview(app_service.learning,sid)
    app_service.write_course_answers(cid,[{'exercise_id':ids[0],'answer_text':''}],'DRAFT_SAVE','empty-draft',study_session_id=sid)
    assert not preview(app_service.learning,sid)['can_restart']
    with pytest.raises(DomainError) as caught:restart(app_service.learning,sid,info['expected_version'],info['expected_content_hash'],'unsafe-restart')
    assert caught.value.code=='STUDY_RESTART_BLOCKED'
    assert app_service.course_study_detail(sid)['study']['is_current']


def test_restart_cas_and_source_failure_preserve_active_round(app_service,study_course):
    from studyflow.modules.learning.restart import preview, restart
    cid,lessons,_=study_course;sid=app_service.open_course_study(cid,'cas-open')['study']['id']
    info=preview(app_service.learning,sid);app_service.save_study_progress(sid,lessons[0],3,'later')
    with pytest.raises(DomainError) as caught:restart(app_service.learning,sid,info['expected_version'],info['expected_content_hash'],'cas-restart')
    assert caught.value.code=='VERSION_CONFLICT'
    latest=preview(app_service.learning,sid)
    (app_service.settings.workspace_root/'content/unit-1.md').write_text('# source changed',encoding='utf-8')
    with pytest.raises(DomainError) as caught:restart(app_service.learning,sid,latest['expected_version'],latest['expected_content_hash'],'source-cas')
    assert caught.value.code=='COURSE_CONTENT_CONFLICT'
    (app_service.settings.workspace_root/'content/unit-1.md').unlink()
    assert not preview(app_service.learning,sid)['can_restart']
    assert app_service.course_study_detail(sid)['study']['is_current']


def test_installation_discovers_exact_paths_and_missing_resources(tmp_path,app_service):
    from studyflow.infrastructure.installation import installation_info
    folder=tmp_path/'安装 目录'/'binaries';folder.mkdir(parents=True)
    engine=folder/'studyflow-engine.exe';engine.write_bytes(b'test')
    cli=folder/'studyflow.exe';cli.write_bytes(b'test')
    skill=folder/'studyflow-agent'/'SKILL.md';skill.parent.mkdir();skill.write_text('test',encoding='utf-8')
    info=installation_info(app_service.settings,executable=engine,frozen=True)
    assert info['cli_argv']==[str(cli)] and info['skill_path']==str(skill)
    assert info['agent_ready'] and info['workspace']==str(app_service.settings.workspace_root.resolve())
    skill.unlink();assert not installation_info(app_service.settings,executable=engine,frozen=True)['agent_ready']


def test_restart_preview_does_not_acquire_writer_lease(app_service,study_course,monkeypatch):
    from studyflow.modules.learning.restart import preview
    cid,_,_=study_course;sid=app_service.open_course_study(cid,'read-only-preview')['study']['id']
    monkeypatch.setattr('studyflow.infrastructure.leases.workspace_lease',lambda *args: (_ for _ in ()).throw(AssertionError('writer lease in preview')))
    assert preview(app_service.learning,sid)['can_restart']


def test_restart_transaction_failure_keeps_old_round_and_no_partial_receipt(app_service,study_course,monkeypatch):
    from studyflow.modules.learning.restart import preview,restart
    from studyflow.modules.learning.models import CourseWriteReceipt
    cid,_,_=study_course;sid=app_service.open_course_study(cid,'rollback-preview')['study']['id'];info=preview(app_service.learning,sid)
    with monkeypatch.context() as patch:
        patch.setattr(app_service.learning,'_event',lambda *args:(_ for _ in ()).throw(RuntimeError('synthetic write failure')))
        with pytest.raises(RuntimeError):restart(app_service.learning,sid,info['expected_version'],info['expected_content_hash'],'rollback-restart')
    assert app_service.course_study_detail(sid)['study']['is_current']
    with app_service.session(read_only=True) as db:
        assert len(db.scalars(select(CourseStudySession)).all())==1
        assert not db.scalar(select(CourseWriteReceipt.id).where(CourseWriteReceipt.idempotency_key=='rollback-restart'))


def test_restart_engine_schema_and_strict_unknown_field_rejection(app_service,study_course):
    from studyflow.engine import StudyFlowEngine
    cid,_,_=study_course;sid=app_service.open_course_study(cid,'engine-restart')['study']['id']
    engine=StudyFlowEngine(service=app_service)
    caps=engine.handle({'id':1,'method':'system.capabilities'})['data']
    assert 'studyflow.course-package/3' in caps['content']['course_package_schemas']
    assert {'course.study.restart.preview','course.study.restart'}.issubset({c['method'] for c in caps['capabilities']})
    schema=engine.handle({'id':2,'method':'system.schema','params':{'method':'course.study.restart'}})
    assert schema['ok'] and 'expected_content_hash' in schema['data']['methods']['course.study.restart']['properties']
    denied=engine.handle({'id':3,'method':'course.study.restart.preview','params':{'study_session_id':sid,'force':True}})
    assert not denied['ok'] and denied['error']['code']=='INVALID_ARGUMENT'
    assert engine.handle({'id':4,'method':'course.study.restart.preview','params':{'study_session_id':sid}})['data']['can_restart']
    assert engine.handle({'id':5,'method':'system.installation'})['data']['agent_ready']
    engine.close()


def test_details_v3_preserves_english_mode():
    data=detailed_package();data['course']['learning_mode']='english'
    for ex in data['lessons'][0]['exercises']:ex['english']={'target':'I like tea.','objective_ids':['likes']}
    assert validate_package(data)['course']['learning_mode']=='english'


def test_confirmed_restart_receipt_does_not_count_as_an_answer(app_service,study_course):
    from studyflow.modules.learning.restart import preview,restart
    cid,_,_=study_course;old=app_service.open_course_study(cid,'repeated-safe-open')['study']['id']
    info=preview(app_service.learning,old);fresh=restart(app_service.learning,old,info['expected_version'],info['expected_content_hash'],'first-safe-restart')
    again=preview(app_service.learning,fresh['study']['id']);assert again['can_restart']
    latest=restart(app_service.learning,fresh['study']['id'],again['expected_version'],again['expected_content_hash'],'second-explicit-restart')
    assert latest['study']['revision']==3
    assert app_service.course_study_detail(fresh['study']['id'])['course']['study_status']=='ABANDONED'


def test_details_note_excerpt_keeps_exact_frozen_block_source(app_service,tmp_path):
    app_service.create_plan_line('Testing')
    imported=app_service.import_course_package(package_file(tmp_path,detailed_package()))
    study=app_service.open_course_study(imported['course_id'],'details-excerpt');sid=study['study']['id'];lid=study['lessons'][0]['id'];pid=study['course']['plan_line_id']
    blocks=[{'id':'excerpt-summary','text':'我的理解','quote':'先记住结论。','course_id':imported['course_id'],'lesson_id':lid,'source_study_id':sid,'source_block_id':'detail'}]
    app_service.save_plan_notebook(pid,blocks,0,'details-note')
    result=app_service.plan_notebook(pid)
    assert result['blocks'][0]['source_block_id']=='detail' and result['blocks'][0]['content_hash']==study['study']['content_hash']
    from studyflow.modules.learning.restart import preview,restart
    info=preview(app_service.learning,sid);restart(app_service.learning,sid,info['expected_version'],info['expected_content_hash'],'details-note-restart')
    retained=app_service.plan_notebook(pid)['blocks'][0]
    assert retained['source_study_id']==sid and retained['quote']=='先记住结论。'


def test_restart_current_course_view_resets_reading_but_history_retains_it(app_service,study_course):
    from studyflow.modules.learning.restart import preview,restart
    cid,lessons,_=study_course;sid=app_service.open_course_study(cid,'course-progress-open')['study']['id']
    app_service.save_study_progress(sid,lessons[1],100,'read-confirmed')
    info=preview(app_service.learning,sid);restart(app_service.learning,sid,info['expected_version'],info['expected_content_hash'],'course-progress-restart')
    assert app_service.course_detail(cid)['course']['reading_percent']==0
    assert all(l['progress']['status']=='NOT_STARTED' for l in app_service.course_detail(cid)['lessons'])
    assert app_service.course_study_detail(sid)['lessons'][1]['progress']['progress_percent']==100

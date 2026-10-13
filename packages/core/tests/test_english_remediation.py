import copy
import json
import pytest
from sqlalchemy import select, func
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.content import validate_package
from studyflow.modules.courses.models import Course
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate, EnglishErrorEvidence
from test_english_specialty import install


def progressive_package():
    stages=[('word','vocabulary','read'),('chunk','chunk','a book'),('base','pattern','I read a book.'),('change','variation','He reads a book.'),('fresh','transfer','She reads every day.')]
    return {'schema':'studyflow.course-package/4','package_id':'remediation-demo','plan_line':'英语试验',
        'course':{'title':'主语变化与动词形式','learning_mode':'english','summary':'从词汇到新的表达。'},
        'lessons':[{'id':'agreement','title':'第三人称单数','blocks':[{'id':'rule','type':'concept','title':'必要规则','body':'一般现在时，第三人称单数主语后的动词通常使用相应的单数形式。'}],
          'exercises':[{'id':key,'title':key,'prompt':'合成中文提示 '+key,'english':{'target':target,'objective_ids':['agreement'],'progression':{'chain_id':'agreement','stage':stage}}} for key,stage,target in stages]}]}


def source(app_service,tmp_path):
    original,opened=install(app_service,tmp_path);sid=opened['study']['id'];ex=opened['lessons'][0]['exercises'][0]['id']
    saved=app_service.english.save(sid,ex,'I lik tea',0,'source-draft')
    app_service.english.check(sid,ex,saved['answer_version'],'source-check')
    with app_service.session(read_only=True) as db:
        agg=db.scalar(select(EnglishErrorAggregate));ev=db.scalar(select(EnglishErrorEvidence))
        selected={'aggregate_id':agg.id,'expected_version':agg.version,'evidence_ids':[ev.id]}
    package=tmp_path/'remediation.json';package.write_text(json.dumps(progressive_package(),ensure_ascii=False),encoding='utf-8')
    request={'plan_line_id':original['plan_id'],'path':str(package),'objective_ids':['agreement'],'rationale':'合成例：针对主语与动词形式做必要基础和变式练习。','sources':[selected]}
    return original,request


def test_progression_is_versioned_and_linear():
    data=progressive_package();assert validate_package(data)==data
    for version in ('2','3'):
        bad=copy.deepcopy(data);bad['schema']='studyflow.course-package/'+version
        with pytest.raises(DomainError):validate_package(bad)
    bad=copy.deepcopy(data);bad['lessons'][0]['exercises'][0]['english']['progression']['stage']='magic'
    with pytest.raises(DomainError):validate_package(bad)


def test_remediation_preview_read_only_and_publish_replay(app_service,tmp_path):
    original,request=source(app_service,tmp_path)
    preview=app_service.remediation.preview(**request)
    assert preview['valid'] and preview['source_count']==1
    with app_service.session(read_only=True) as db:assert db.scalar(select(func.count(Course.id)))==1
    payload={**request,'preview_hash':preview['preview_hash'],'idempotency_key':'remediation-once'}
    result=app_service.remediation.publish(**payload)
    assert app_service.remediation.publish(**payload)==result
    plan=app_service.plan_detail(original['plan_id'])
    assert plan['plan']['course_total']==1 and len(plan['courses'])==1
    assert plan['plan']['supplement_total']==1
    assert app_service.dashboard()['current_course'].id==original['course_id']
    view=app_service.remediation.get(result['course_id'])
    assert view['sources'][0]['aggregate_id']==request['sources'][0]['aggregate_id']
    assert view['learning_status']=='NOT_STARTED'


def test_source_change_rejected_and_no_partial_course(app_service,tmp_path):
    _,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    with app_service.session() as db:db.get(EnglishErrorAggregate,request['sources'][0]['aggregate_id']).version+=1
    with pytest.raises(DomainError) as error:app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='stale')
    assert error.value.code=='VERSION_CONFLICT'
    with app_service.session(read_only=True) as db:assert db.scalar(select(func.count(Course.id)))==1


def test_cross_plan_and_invalid_evidence_rejected(app_service,tmp_path):
    _,request=source(app_service,tmp_path);other=app_service.create_plan_line('其他计划')
    with pytest.raises(DomainError):app_service.remediation.preview(**{**request,'plan_line_id':other.id})
    with app_service.session() as db:db.get(EnglishErrorEvidence,request['sources'][0]['evidence_ids'][0]).valid_error=False
    with pytest.raises(DomainError):app_service.remediation.preview(**request)

@pytest.mark.parametrize('change',['reverse','missing-start','missing-transfer','missing-stage','unknown-field'])
def test_remediation_sequence_and_legacy_constraints(app_service,tmp_path,change):
    _,request=source(app_service,tmp_path);data=progressive_package();items=data['lessons'][0]['exercises']
    if change=='reverse':items.reverse()
    if change=='missing-start':items.pop(0)
    if change=='missing-transfer':items.pop()
    if change=='missing-stage':items[0]['english'].pop('progression')
    if change=='unknown-field':items[0]['english']['progression']['layout']='custom'
    Path=__import__('pathlib').Path;Path(request['path']).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(DomainError):app_service.remediation.preview(**request)


def test_publication_rolls_back_on_post_registration_failure(app_service,tmp_path,monkeypatch):
    from studyflow.modules.mistakes.remediation.models import EnglishRemediationCourse,EnglishRemediationSource
    _,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    monkeypatch.setattr(app_service.remediation,'_event',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('synthetic transaction failure')))
    with pytest.raises(RuntimeError):app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='rollback')
    with app_service.session(read_only=True) as db:
        assert db.scalar(select(func.count(Course.id)))==1
        assert db.scalar(select(func.count(EnglishRemediationCourse.course_id)))==0
        assert db.scalar(select(func.count(EnglishRemediationSource.id)))==0


def test_completed_supplement_preserves_original_error_and_mainline(app_service,tmp_path):
    original,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    result=app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='complete-publish')
    opened=app_service.open_course_study(result['course_id'],'supplement-open');sid=opened['study']['id'];view=app_service.english.get(sid)
    assert [i['progression']['stage'] for i in view['items']]==['vocabulary','chunk','pattern','variation','transfer']
    assert all('target' not in i for i in view['items'])
    versions={}
    for item,ex in zip(view['items'],progressive_package()['lessons'][0]['exercises']):
        save=app_service.english.save(sid,item['exercise_id'],ex['english']['target'],0,'supp-save-'+ex['id'])
        assert app_service.english.check(sid,item['exercise_id'],save['answer_version'],'supp-check-'+ex['id'])['matched']
        versions[item['exercise_id']]=save['answer_version']
    app_service.english.submit(sid,'supp-complete',versions)
    detail=app_service.remediation.get(result['course_id']);assert detail['learning_status']=='COMPLETED'
    assert detail['transfer_status']=='UNASSISTED_PASS'
    with app_service.session(read_only=True) as db:
        agg=db.get(EnglishErrorAggregate,request['sources'][0]['aggregate_id'])
        assert not agg.archived and agg.version==request['sources'][0]['expected_version']
        assert db.scalar(select(func.count(Course.id)))==2
    assert app_service.plan_detail(original['plan_id'])['plan']['course_total']==1


def test_explicit_supplement_schedule_cannot_be_main_focus(app_service,tmp_path):
    from datetime import date
    from studyflow.modules.planning.management import edit_plan
    original,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    result=app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='schedule-publish')
    edit_plan(app_service.planning,original['plan_id'],1,'schedule-supp','SCHEDULE',{'course_id':result['course_id'],'date':date.today().isoformat()})
    dashboard=app_service.dashboard();assert dashboard['current_course'].id==original['course_id']
    assert next(c for c in dashboard['courses'] if c.id==result['course_id']).plan_track=='SUPPLEMENT'
    with pytest.raises(DomainError):edit_plan(app_service.planning,original['plan_id'],2,'wrong-focus','UPDATE',{'focus_course_id':result['course_id']})
    edit_plan(app_service.planning,original['plan_id'],2,'main-reorder','REORDER',{'course_ids':[original['course_id']]})


def test_strict_remediation_transport_and_discovery(app_service,tmp_path):
    from studyflow.engine import StudyFlowEngine
    engine=StudyFlowEngine(service=app_service)
    try:
        _,request=source(app_service,tmp_path)
        response=engine.handle({'id':'preview','method':'course.remediation.preview','params':request});assert response['ok']
        bad=engine.handle({'id':'bad','method':'course.remediation.list','params':{'plan_line_id':request['plan_line_id'],'limit':True}});assert not bad['ok']
        schema=engine.handle({'id':'schema','method':'system.schema','params':{'method':'course.remediation.publish'}})
        assert schema['ok'] and 'course.remediation.publish' in schema['data']['methods']
    finally:engine.close()


def test_source_purge_requires_explicit_dependent_course_selection(app_service,tmp_path):
    original,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    result=app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='purge-publish')
    with pytest.raises(DomainError) as error:app_service.purge_courses(confirm=True,course_ids=[original['course_id']])
    assert error.value.code=='COURSE_HAS_REMEDIATION_DEPENDENCIES'
    app_service.purge_courses(confirm=True,course_ids=[original['course_id'],result['course_id']])
    with app_service.session(read_only=True) as db:assert db.scalar(select(func.count(Course.id)))==0


def test_preview_does_not_acquire_a_writer_lease(app_service,tmp_path,monkeypatch):
    _,request=source(app_service,tmp_path)
    def forbidden(*a,**kw):raise AssertionError('preview must be read-only')
    monkeypatch.setattr('studyflow.infrastructure.leases.workspace_lease',forbidden)
    assert app_service.remediation.preview(**request)['valid']


def test_duplicate_key_with_different_request_is_not_republished(app_service,tmp_path):
    _,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='stable-key')
    with pytest.raises(DomainError) as error:app_service.remediation.publish(**{**request,'rationale':'Different purpose'},preview_hash=preview['preview_hash'],idempotency_key='stable-key')
    assert error.value.code=='IDEMPOTENCY_KEY_CONFLICT'


def test_progressive_revision_keeps_frozen_stage_and_source(app_service,tmp_path):
    from studyflow.modules.courses.revisions import preview, apply
    original,request=source(app_service,tmp_path);checked=app_service.remediation.preview(**request)
    published=app_service.remediation.publish(**request,preview_hash=checked['preview_hash'],idempotency_key='revision-publish')
    opened=app_service.open_course_study(published['course_id'],'revision-open')
    data=progressive_package();data['lessons'][0]['blocks'][0]['body']='新版讲解；冻结轮次依旧读旧版。'
    file=tmp_path/'changed.json';file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    info=preview(app_service.courses,published['course_id'],file,1)
    apply(app_service.courses,published['course_id'],file,1,info['preview_hash'],'revision-apply')
    old=app_service.english.get(opened['study']['id']);assert old['items'][0]['progression']['stage']=='vocabulary' and old['course']['source_changed']
    assert '新版' not in old['groups'][0]['blocks'][0]['body']
    data['lessons'][0]['exercises'][-1]['english']['progression']['stage']='variation';file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(DomainError):preview(app_service.courses,published['course_id'],file,2)
    assert app_service.remediation.get(published['course_id'])['sources'][0]['aggregate_id']==request['sources'][0]['aggregate_id']


def test_assisted_transfer_is_not_independent_pass(app_service,tmp_path):
    _,request=source(app_service,tmp_path);preview=app_service.remediation.preview(**request)
    published=app_service.remediation.publish(**request,preview_hash=preview['preview_hash'],idempotency_key='assisted-publish')
    opened=app_service.open_course_study(published['course_id'],'assisted-open');sid=opened['study']['id'];item=app_service.english.get(sid)['items'][-1]
    app_service.english.reveal(sid,item['exercise_id'],'show-transfer-answer')
    save=app_service.english.save(sid,item['exercise_id'],'She reads every day.',1,'assisted-answer')
    app_service.english.check(sid,item['exercise_id'],save['answer_version'],'assisted-check')
    result=app_service.remediation.get(published['course_id']);assert result['transfer_status']=='ASSISTED_PASS' and result['transfer_unassisted_passed']==0


def test_mainline_v4_course_revision_does_not_require_supplemental_foundation(app_service, tmp_path):
    from studyflow.modules.courses.revisions import preview, apply
    data = progressive_package()
    plan_id = app_service.create_plan_line(data['plan_line']).id
    data['package_id'] = 'mainline-pattern-v4'
    data['lessons'][0]['exercises'] = [data['lessons'][0]['exercises'][2]]
    path = tmp_path / 'main-pattern.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    imported = app_service.import_course_package(path)
    data['lessons'][0]['blocks'][0]['body'] = '修订主线课程的句型讲解。'
    changed = tmp_path / 'main-pattern-revised.json'
    changed.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    proposed = preview(app_service.courses, imported['course_id'], changed, 1)
    applied = apply(app_service.courses, imported['course_id'], changed, 1, proposed['preview_hash'], 'main-pattern-revised')
    assert applied['revision'] == 2
    plan = app_service.plan_detail(plan_id)
    assert plan['plan']['course_total'] == 1 and plan['plan']['supplement_total'] == 0


def test_supplement_only_plan_does_not_become_automatic_mainline(app_service, tmp_path):
    from datetime import date
    from sqlalchemy import delete
    from studyflow.modules.planning.models import PlanCourseItem
    from studyflow.modules.planning.management import edit_plan
    original, request = source(app_service, tmp_path)
    checked = app_service.remediation.preview(**request)
    published = app_service.remediation.publish(**request, preview_hash=checked['preview_hash'], idempotency_key='only-supplement')
    with app_service.session() as db:
        db.execute(delete(PlanCourseItem).where(PlanCourseItem.course_id == original['course_id']))
    edit_plan(app_service.planning, original['plan_id'], 1, 'only-supplement-schedule', 'SCHEDULE', {'course_id': published['course_id'], 'date': date.today().isoformat()})
    detail = app_service.plan_detail(original['plan_id'])
    assert detail['plan']['course_total'] == 0 and detail['plan']['supplement_total'] == 1
    assert detail['current_course'] is None
    dashboard = app_service.dashboard(plan_line_id=original['plan_id'])
    assert dashboard['current_course'] is None and dashboard['course_total'] == 0
    assert len(dashboard['courses']) == 1 and dashboard['courses'][0].id == published['course_id']


def test_transfer_correction_cannot_erase_assistance_in_same_round(app_service, tmp_path):
    _, request = source(app_service, tmp_path)
    preview = app_service.remediation.preview(**request)
    published = app_service.remediation.publish(**request, preview_hash=preview['preview_hash'], idempotency_key='assisted-revision-publish')
    opened = app_service.open_course_study(published['course_id'], 'assisted-revision-open')
    sid = opened['study']['id']
    item = app_service.english.get(sid)['items'][-1]
    revealed = app_service.english.reveal(sid, item['exercise_id'], 'assisted-revision-reveal')
    saved = app_service.english.save(sid, item['exercise_id'], 'She read every day', revealed['answer_version'], 'assisted-revision-wrong')
    app_service.english.check(sid, item['exercise_id'], saved['answer_version'], 'assisted-revision-check')
    requested = app_service.english.request_review(sid, item['exercise_id'], saved['answer_version'], 'assisted-revision-request')
    app_service.write_review(requested['submission_id'], '请修正动词形式。', decision='REVISION_REQUIRED', idempotency_key='assisted-revision-review')
    latest = app_service.english.get(sid)['items'][-1]
    corrected = app_service.english.save(sid, item['exercise_id'], 'She reads every day', latest['answer_version'], 'assisted-revision-corrected')
    app_service.english.check(sid, item['exercise_id'], corrected['answer_version'], 'assisted-revision-corrected-check')
    result = app_service.remediation.get(published['course_id'])
    assert result['transfer_status'] == 'ASSISTED_PASS' and result['transfer_unassisted_passed'] == 0

"""Q2/Q3/Q4 integration uses only disposable synthetic workspaces."""
import copy
import json
import pytest
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.content import validate_package, fallback_markdown
from test_course_packages import sample, package_file


def upgraded():
    data=sample();data['schema']='studyflow.course-package/5'
    data['lessons'][0]['blocks'][0]={'id':'idea','type':'concept','title':'CPU roles','sections':[
        {'id':'core','title':'必要定义','role':'main','body':'CPU executes instructions.'},
        {'id':'why','title':'补充推导','role':'supplement','summary':'理解PC为什么指向地址。','body':'PC holds the next address.','children':[
            {'id':'boundary','title':'边界','role':'main','body':'Address is not instruction.'}]}]}
    data['lessons'][0]['exercises'][0]['review_reference']={'answer':'PC holds an address.','explanation':'PC保存下一条指令的地址，不是指令内容。','criteria':['区分地址与内容'],'accepted_variants':['下一条指令的位置'],'source':'合成教材 §1'}
    return data


def install(service,tmp_path):
    service.create_plan_line('Testing');result=service.import_course_package(package_file(tmp_path,upgraded()))
    opened=service.open_course_study(result['course_id'],'q234-open',plan_line_id=result['plan_id'])
    return result,opened


def test_sections_and_reference_render_without_default_answer_leak(app_service,tmp_path):
    result,opened=install(app_service,tmp_path)
    assert opened['lessons'][0]['content_blocks'][0]['sections'][1]['summary_html']
    assert 'review_reference' not in opened['lessons'][0]['exercises'][0]
    assert 'review_reference' not in app_service.course_detail(result['course_id'])['lessons'][0]['exercises'][0]
    assert 'PC holds an address.' not in fallback_markdown(upgraded()['lessons'][0])


@pytest.mark.parametrize('change',['old','both','empty','duplicate','role','summary','depth','count','budget','unknown','english-reference'])
def test_package5_rejects_invalid_structure(change):
    data=upgraded();block=data['lessons'][0]['blocks'][0]
    if change=='old':data['schema']='studyflow.course-package/4'
    if change=='both':block['body']='two competing bodies'
    if change=='empty':block['sections']=[]
    if change=='duplicate':block['sections'][1]['children'][0]['id']='core'
    if change=='role':block['sections'][0]['role']='hidden'
    if change=='summary':del block['sections'][1]['summary']
    if change=='depth':block['sections'][1]['children'][0]['children']=[{'id':'deep','title':'deep','role':'main','body':'x'}]
    if change=='count':block['sections']=[{'id':f's{i}','title':'s','role':'main','body':'x'} for i in range(41)]
    if change=='budget':block['sections'][0]['body']='x'*20000
    if change=='unknown':block['sections'][0]['onclick']='evil'
    if change=='english-reference':data['lessons'][0]['exercises'][0]['review_reference']['not_supported']='x'
    with pytest.raises(DomainError):validate_package(data)


def test_reference_freeze_fingerprint_corrected_version_and_hint(app_service,tmp_path):
    from studyflow.modules.courses.references.service import read_reference, view_reference
    from studyflow.modules.courses.revisions import preview,apply
    result,opened=install(app_service,tmp_path);sid=opened['study']['id'];eid=opened['lessons'][0]['exercises'][0]['id']
    ref=read_reference(app_service.learning,study_session_id=sid,exercise_id=eid)
    assert ref['available'] and ref['content_revision']==1 and not ref['hint_used']
    first=view_reference(app_service.learning,study_session_id=sid,exercise_id=eid)
    assert first['hint_used'] and view_reference(app_service.learning,study_session_id=sid,exercise_id=eid)['reference_hash']==first['reference_hash']
    updated=upgraded();updated['lessons'][0]['exercises'][0]['review_reference']['explanation']='更正：地址。'
    path=package_file(tmp_path,updated);p=preview(app_service.courses,result['course_id'],path,1)
    apply(app_service.courses,result['course_id'],path,1,p['preview_hash'],'reference-corrected')
    assert read_reference(app_service.learning,study_session_id=sid,exercise_id=eid)['reference']['explanation']!='更正：地址。'
    newref=read_reference(app_service.learning,study_session_id=sid,exercise_id=eid,reference_revision=2)
    assert newref['reference']['explanation']=='更正：地址。' and newref['is_correction']
    updated['lessons'][0]['exercises'][0]['prompt']='Changed question with same id'
    path=package_file(tmp_path,updated);p=preview(app_service.courses,result['course_id'],path,2)
    apply(app_service.courses,result['course_id'],path,2,p['preview_hash'],'question-changed')
    with pytest.raises(DomainError) as exc:read_reference(app_service.learning,study_session_id=sid,exercise_id=eid,reference_revision=3)
    assert exc.value.code=='REFERENCE_MISMATCH'


def test_review_records_matching_reference_and_replay(app_service,tmp_path):
    from studyflow.modules.courses.references.service import read_reference
    result,opened=install(app_service,tmp_path);sid=opened['study']['id'];eid=opened['lessons'][0]['exercises'][0]['id']
    written=app_service.write_course_answers(result['course_id'],[{'exercise_id':eid,'answer_text':'instruction'}],'SUBMIT','answer',study_session_id=sid)
    with app_service.session(read_only=True) as db:
        from studyflow.modules.learning.models import Submission
        submission=db.scalar(select(Submission).where(Submission.study_session_id==sid));subid=submission.id
    ref=read_reference(app_service.learning,submission_id=subid)
    args=dict(submission_id=subid,summary='地址而非内容',decision='REVISION_REQUIRED',idempotency_key='review',reference_hash=ref['reference_hash'])
    review=app_service.reviews.write_review(**args)
    assert review.reference_hash==ref['reference_hash'] and review.reference_revision==1
    assert app_service.reviews.write_review(**args).id==review.id
    with pytest.raises(DomainError):app_service.reviews.write_review(**{**args,'reference_hash':'0'*64})


def test_plan_groups_are_membership_scoped_and_restore_preserves_history(app_service,tmp_path):
    from studyflow.modules.planning.management import edit_plan
    from studyflow.modules.planning.repository import ensure_course_membership
    from studyflow.modules.planning.models import PlanLine
    from studyflow.modules.courses.models import Course
    result,opened=install(app_service,tmp_path);other=app_service.create_plan_line('Other')
    with app_service.session() as db:ensure_course_membership(db,db.get(PlanLine,other.id),db.get(Course,result['course_id']))
    sid=opened['study']['id'];eid=opened['lessons'][0]['exercises'][0]['id']
    app_service.write_course_answers(result['course_id'],[{'exercise_id':eid,'answer_text':'anything'}],'SUBMIT','group-answer',study_session_id=sid)
    a=app_service.plan_detail(result['plan_id']);b=app_service.plan_detail(other.id)
    assert a['courses'][0]['learning_group']=='COMPLETED'
    assert b['courses'][0]['learning_group']=='PENDING' and not b['courses'][0]['learning_submitted']
    assert a['courses'][0]['study_status']=='WAITING_REVIEW'
    version=a['plan']['version'];args=dict(plan_line_id=result['plan_id'],expected_version=version,idempotency_key='move-other',operation='COURSE_POSITION',values={'course_id':result['course_id'],'position':'OTHER','reason':'暂缓'})
    moved=edit_plan(app_service.planning,**args)
    assert edit_plan(app_service.planning,**args)==moved
    after=app_service.plan_detail(result['plan_id']);assert after['courses'][0]['learning_group']=='OTHER' and not after['current_course']
    with pytest.raises(DomainError):edit_plan(app_service.planning,**{**args,'values':{**args['values'],'reason':'different'}})
    edit_plan(app_service.planning,result['plan_id'],moved['version'],'restore-other','COURSE_POSITION',{'course_id':result['course_id'],'position':'NORMAL'})
    assert app_service.plan_detail(result['plan_id'])['courses'][0]['learning_group']=='COMPLETED'
    subid=app_service.course_study_detail(sid)['lessons'][0]['exercises'][0]['latest_submission']['id']
    assert app_service.submission_detail(subid)['answer_text']=='anything'


def test_learning_evidence_is_bounded_and_does_not_guess_mastery(app_service,tmp_path):
    from studyflow.modules.learning.evidence import read_evidence
    result,opened=install(app_service,tmp_path)
    evidence=read_evidence(app_service.learning,plan_line_id=result['plan_id'],limit=1)
    assert len(evidence['items'])==1 and evidence['items'][0]['mastery']=='not_inferred'
    assert evidence['items'][0]['hint_information']=='recorded_since_1.8'
    with pytest.raises(DomainError):read_evidence(app_service.learning,plan_line_id=result['plan_id'],limit=101)



def test_reference_section_provenance_and_old_round_hint_uncertainty(app_service,tmp_path):
    from studyflow.modules.learning.models import CourseStudySession
    from studyflow.modules.learning.notebook.sources import verify
    from studyflow.modules.learning.notebook_queries import source
    from studyflow.modules.courses.references.service import read_reference
    result,opened=install(app_service,tmp_path);sid=opened["study"]["id"];lid=opened["lessons"][0]["id"];eid=opened["lessons"][0]["exercises"][0]["id"]
    registration={"id":"section-note","original":"PC holds the next address.","course_id":result["course_id"],"lesson_id":lid,"source_study_id":sid,"source_block_id":"idea","source_section_id":"why"}
    with app_service.session() as db:
        checked=verify(db,result["plan_id"],registration);assert checked["verification"]=="VERIFIED"
        before=db.get(CourseStudySession,sid).content_hash;db.get(CourseStudySession,sid).hint_tracking_enabled=False
    ref=read_reference(app_service.learning,study_session_id=sid,exercise_id=eid)
    assert ref["hint_information"]=="legacy_unknown"
    assert app_service.course_study_detail(sid)["study"]["content_hash"]==before
    assert not app_service.course_study_detail(sid)["study"]["source_changed"]
    assert source(app_service.learning,sid,lid,"idea","why")["section"]["id"]=="why"
    with app_service.session(read_only=True) as db:
        with pytest.raises(DomainError):verify(db,result["plan_id"],{**registration,"source_section_id":"core"})

def test_corrected_reference_requires_reason_and_records_frozen_version(app_service,tmp_path):
    from studyflow.modules.courses.references.service import read_reference
    from studyflow.modules.courses.revisions import preview,apply
    result,opened=install(app_service,tmp_path);sid=opened['study']['id'];eid=opened['lessons'][0]['exercises'][0]['id']
    answer=app_service.write_course_answers(result['course_id'],[{'exercise_id':eid,'answer_text':'test'}],'SUBMIT','correction-answer',study_session_id=sid)['submissions'][0]['id']
    data=upgraded();data['lessons'][0]['exercises'][0]['review_reference']['explanation']='作者更正理由。';path=package_file(tmp_path,data);p=preview(app_service.courses,result['course_id'],path,1);apply(app_service.courses,result['course_id'],path,1,p['preview_hash'],'correction-revision')
    reference=read_reference(app_service.learning,submission_id=answer,reference_revision=2)
    args=dict(submission_id=answer,summary='检查完成',decision='PASSED',idempotency_key='corrected-review',reference_hash=reference['reference_hash'],reference_revision=2)
    with pytest.raises(DomainError):app_service.reviews.write_review(**args)
    review=app_service.reviews.write_review(**args,reference_reason='原解释术语不准确，题面指纹不变。')
    assert review.reference_revision==2 and review.reference_reason
    assert app_service.submission_detail(answer)['reviews'][0]['reference_hash']==reference['reference_hash']


def test_other_courses_reject_new_schedule_and_existing_round_answer_remains_writable(app_service,tmp_path):
    from datetime import date
    from studyflow.modules.planning.management import edit_plan,list_schedule
    result,opened=install(app_service,tmp_path);pid=result['plan_id'];cid=result['course_id'];sid=opened['study']['id'];eid=opened['lessons'][0]['exercises'][0]['id']
    plan=app_service.plan_detail(pid)['plan'];scheduled=edit_plan(app_service.planning,pid,plan['version'],'schedule-test','SCHEDULE',{'course_id':cid,'date':date.today().isoformat()})
    moved=edit_plan(app_service.planning,pid,scheduled['version'],'hold-test','COURSE_POSITION',{'course_id':cid,'position':'OTHER','reason':'资料待补'})
    schedule=list_schedule(app_service.planning,pid)['items'][0]
    assert schedule['status']=='CANCELLED'
    with pytest.raises(DomainError):edit_plan(app_service.planning,pid,moved['version'],'reschedule-rejected','RESCHEDULE',{'schedule_id':schedule['id'],'date':date.today().isoformat()})
    with pytest.raises(DomainError):edit_plan(app_service.planning,pid,moved['version'],'schedule-rejected','SCHEDULE',{'course_id':cid,'date':date.today().isoformat()})
    saved=app_service.write_course_answers(cid,[{'exercise_id':eid,'answer_text':'保留正在编辑的答案'}],'DRAFT_SAVE','active-save',study_session_id=sid)
    assert saved['submissions']

import copy
import json
import pytest
from sqlalchemy import select, func
from typer.testing import CliRunner
from studyflow.cli import app
from studyflow.modules.courses.models import Course, Lesson
from studyflow.shared.domain import DomainError
from studyflow.modules.courses.content import validate_package


def sample():
    return {"schema":"studyflow.course-package/1","package_id":"cpu-lesson-v1","plan_line":"Testing","course":{"title":"CPU"},"lessons":[{"id":"cpu","title":"CPU roles","blocks":[{"id":"idea","type":"concept","title":"Concept","body":"The **CPU** executes instructions.<script>alert(1)</script>"},{"id":"compare","type":"comparison","title":"Registers","columns":["Name","Purpose"],"rows":[["PC","Address"],["IR","Instruction"]]},{"id":"flow","type":"steps","title":"Execution","items":[{"title":"Fetch","body":"Read instruction"}]},{"id":"example","type":"example","title":"Example","given":"PC=8","steps":[{"title":"Advance","body":"8+4"}],"conclusion":"PC=12"},{"id":"warning","type":"callout","title":"Do not confuse","body":"Address is not instruction","tone":"warning"},{"id":"recap","type":"summary","title":"Remember","items":["PC holds address"]},{"id":"practice","type":"practice","title":"Try it","exercise_ids":["q1"]}],"exercises":[{"id":"q1","title":"PC","prompt":"What does PC hold?"}]}]}


def package_file(tmp_path, data=None):
    path=tmp_path/'course.json';path.write_text(json.dumps(data or sample()),encoding='utf-8');return path


def test_validate_has_no_side_effect(monkeypatch,tmp_path):
    path=package_file(tmp_path)
    result=CliRunner().invoke(app,['course','validate-package','--file',str(path),'--format','json'])
    assert result.exit_code==0,result.output
    assert json.loads(result.stdout)['block_total']==7
    assert sorted(p.name for p in tmp_path.iterdir())==['course.json']


def test_atomic_import_replay_render_and_freeze(app_service,tmp_path):
    app_service.create_plan_line('Testing');path=package_file(tmp_path)
    first=app_service.import_course_package(path)
    assert first['created'] and first['exercise_total']==1
    replay=app_service.import_course_package(path)
    assert not replay['created'] and replay['course_id']==first['course_id']
    detail=app_service.course_detail(first['course_id'])
    blocks=detail['lessons'][0]['content_blocks']
    assert len(blocks)==7 and 'alert' not in blocks[0]['body_html']
    assert blocks[-1]['exercise_ids']==[detail['lessons'][0]['exercises'][0]['id']]
    from studyflow.modules.learning.study_sessions import open_study,detail as study_detail
    study=open_study(app_service.learning, first['course_id'], 'test-open')
    sid=study['study']['id']
    assert study['lessons'][0]['content_blocks']==blocks
    p=tmp_path/first['paths'][0];p.write_text(p.read_text(encoding='utf-8').replace('executes instructions','executes changed instructions'),encoding='utf-8')
    frozen=study_detail(app_service.learning,sid)
    assert frozen['study']['source_changed']
    assert frozen['lessons'][0]['content_blocks']==blocks


@pytest.mark.parametrize('case',['unknown','duplicate','missing-ref','row-length','version','script-field'])
def test_invalid_rejected(case):
    data=sample();lesson=data['lessons'][0]
    if case=='unknown':lesson['blocks'][0]['type']='vue'
    if case=='duplicate':lesson['blocks'][1]['id']='idea'
    if case=='missing-ref':lesson['blocks'][-1]['exercise_ids']=['missing']
    if case=='row-length':lesson['blocks'][1]['rows']=[['one']]
    if case=='version':data['schema']='v2'
    if case=='script-field':lesson['blocks'][0]['script']='evil()'
    with pytest.raises(DomainError):validate_package(data)


def test_invalid_later_lesson_does_not_import_prefix(app_service,tmp_path):
    app_service.create_plan_line('Testing');data=sample();second=copy.deepcopy(data['lessons'][0]);second['id']='second';second['blocks'][-1]['exercise_ids']=['missing'];data['lessons'].append(second)
    with pytest.raises(DomainError):app_service.import_course_package(package_file(tmp_path,data))
    assert app_service.list_courses()==[]
    assert not (tmp_path/'content/course-packages').exists()


def test_changed_package_refused(app_service,tmp_path):
    app_service.create_plan_line('Testing');path=package_file(tmp_path);first=app_service.import_course_package(path)
    data=sample();data['lessons'][0]['blocks'][0]['body']='changed';package_file(tmp_path,data)
    with pytest.raises(DomainError,match='不同内容'):app_service.import_course_package(path)
    assert len(app_service.list_courses())==1


def test_database_failure_rolls_back_entire_package(app_service,tmp_path,monkeypatch):
    app_service.create_plan_line('Testing')
    def fail(*args,**kwargs):raise RuntimeError('injected failure before commit')
    monkeypatch.setattr(app_service.courses,'_event',fail)
    with pytest.raises(RuntimeError):app_service.import_course_package(package_file(tmp_path))
    assert app_service.list_courses()==[]
    # Immutable orphan files are replay-safe; no partial course was registered.
    monkeypatch.undo()
    assert app_service.import_course_package(tmp_path/'course.json')['created']


def test_cli_import_package(monkeypatch,app_service,tmp_path):
    import studyflow.cli as cli
    app_service.create_plan_line('Testing');monkeypatch.setattr(cli,'service',lambda:app_service)
    result=CliRunner().invoke(app,['course','import-package','--file',str(package_file(tmp_path)),'--format','json'])
    assert result.exit_code==0,result.output
    assert json.loads(result.stdout)['knowledge_total']==1


def test_block_excerpt_has_verified_anchor(app_service,tmp_path):
    plan=app_service.create_plan_line('Testing');result=app_service.import_course_package(package_file(tmp_path))
    study=app_service.open_course_study(result['course_id'],'notebook-block-open')
    block={'id':'note','text':'My understanding','quote':'PC holds address','source_study_id':study['study']['id'],'course_id':result['course_id'],'lesson_id':study['lessons'][0]['id'],'source_block_id':'recap'}
    saved=app_service.save_plan_notebook(plan.id,[block],0,'block-note-save')
    assert saved['blocks'][0]['source_block_id']=='recap'
    with pytest.raises(DomainError):app_service.save_plan_notebook(plan.id,[{**block,'source_block_id':'idea'}],1,'wrong-anchor')
    with pytest.raises(DomainError):app_service.save_plan_notebook(plan.id,[{**block,'source_block_id':'missing'}],1,'missing-anchor')


@pytest.mark.parametrize('kind,value',[('type',[]),('tone',{}),('exercise-type',[])])
def test_non_scalar_enums_return_domain_error(kind,value):
    data=sample()
    if kind=='type':data['lessons'][0]['blocks'][0]['type']=value
    elif kind=='tone':data['lessons'][0]['blocks'][4]['tone']=value
    else:data['lessons'][0]['exercises'][0]['type']=value
    with pytest.raises(DomainError):validate_package(data)


def test_duplicate_json_keys_rejected(tmp_path):
    from studyflow.modules.courses.content import read_package
    path=tmp_path/'duplicate.json';path.write_text('{"schema":"a","schema":"b"}',encoding='utf-8')
    with pytest.raises(DomainError):read_package(path)


def test_package_lock_rejects_concurrent_publication(app_service,tmp_path):
    from studyflow.modules.courses.packages import package_lock
    app_service.create_plan_line('Testing');path=package_file(tmp_path)
    with package_lock(app_service.settings.workspace_root):
        with pytest.raises(DomainError) as error:app_service.import_course_package(path)
        assert error.value.code=='COURSE_PACKAGE_BUSY'
    assert app_service.import_course_package(path)['created']

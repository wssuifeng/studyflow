"""Immutable course revisions with explicit, content-bound preview/apply."""
import json
from pathlib import Path
import yaml
from sqlalchemy import select, update, func
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.learning.write_contract import digest
from studyflow.modules.learning.models import CourseStudySession
from studyflow.modules.documents.models import Document
from studyflow.infrastructure.markdown import safe_resolve, parse_front_matter, inspect_document
from .models import Course, Lesson, Exercise, CourseRevision
from .packages import inspect_package, package_lock
from .content import SCHEMA, fallback_markdown

def existing_content(service,db,course):
    lessons=db.scalars(select(Lesson).where(Lesson.course_id==course.id,Lesson.included==True).order_by(Lesson.position,Lesson.id)).all()
    previous=db.scalar(select(CourseRevision).where(CourseRevision.course_id==course.id).order_by(CourseRevision.number.desc()))
    mapping=json.loads(previous.mapping_json) if previous else {"lessons":{},"exercises":{}}
    sources=[]
    for row in lessons:
        text=safe_resolve(service.settings.workspace_root,row.markdown_path).read_text(encoding="utf-8")
        meta,body=parse_front_matter(text)
        source=meta.get("structured_lesson")
        exercises=db.scalars(select(Exercise).where(Exercise.lesson_id==row.id,Exercise.included==True).order_by(Exercise.position,Exercise.id)).all()
        if not source:
            source={"id":row.semantic_id or "legacy-"+row.id,"title":row.title,"blocks":[{"id":"legacy","type":"concept","title":row.title,"body":body}],"exercises":[{"id":e.semantic_id or "legacy-"+e.id,"title":e.title,"prompt":e.prompt,"requirements":e.requirements} for e in exercises]}
        if len(source.get("exercises",[]))!=len(exercises):raise DomainError("COURSE_SOURCE_CONFLICT","源材料与题目登记不一致，不能猜测语义映射。")
        mapping["lessons"][source["id"]]=row.id
        for ex,model in zip(source.get("exercises",[]),exercises):mapping["exercises"][source["id"]+":"+ex["id"]]=model.id
        sources.append(source)
    package={"schema":SCHEMA,"package_id":"existing-"+course.id,"plan_line":course.plan_line.name if course.plan_line else "","course":{"title":course.title,"summary":course.summary,"subject":course.subject,"difficulty":course.difficulty},"lessons":sources}
    return package,mapping

def preview(service,course_id,path,expected_revision):
    data,info=inspect_package(path)
    with service.session() as db:
        course=db.get(Course,course_id)
        if not course:raise DomainError("OBJECT_NOT_FOUND","课程不存在。")
        if isinstance(expected_revision,bool) or expected_revision!=course.version:raise DomainError("VERSION_CONFLICT","课程发布版本已变化。")
        if not course.plan_line or data["plan_line"]!=course.plan_line.name:raise DomainError("INVALID_ARGUMENT","修订不能把课程移到其他计划。")
        old,mapping=existing_content(service,db,course)
        old_keys={l["id"] for l in old["lessons"]};new_keys={l["id"] for l in data["lessons"]}
        old_ex={l["id"]+":"+e["id"] for l in old["lessons"] for e in l.get("exercises",[])};new_ex={l["id"]+":"+e["id"] for l in data["lessons"] for e in l.get("exercises",[])}
        result={"course_id":course_id,"expected_revision":expected_revision,"new_revision":expected_revision+1,"content_hash":info["content_hash"],"added_lessons":sorted(new_keys-old_keys),"removed_lessons":sorted(old_keys-new_keys),"added_exercises":sorted(new_ex-old_ex),"removed_exercises":sorted(old_ex-new_ex),"changed_lessons":[l["id"] for l in data["lessons"] if l["id"] in old_keys and l!=next(o for o in old["lessons"] if o["id"]==l["id"])],"order_changed":[l["id"] for l in old["lessons"]]!=[l["id"] for l in data["lessons"]],"affected_study_rounds":db.scalar(select(func.count(CourseStudySession.id)).where(CourseStudySession.course_id==course_id)),"historical_entities_retained":True}
        result["preview_hash"]=digest({"old":old,"new":data,"mapping":mapping,"course_id":course_id,"expected_revision":expected_revision})
        return result

def apply(service,course_id,path,expected_revision,preview_hash,idempotency_key):
    if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160:raise DomainError("INVALID_ARGUMENT","需要稳定发布幂等键。")
    data,info=inspect_package(path)
    request_hash=digest({"course_id":course_id,"data":data,"expected_revision":expected_revision,"preview_hash":preview_hash})
    with package_lock(service.settings.workspace_root):
        with service.session() as db:
            replay=db.scalar(select(CourseRevision).where(CourseRevision.idempotency_key==idempotency_key))
            if replay:
                if replay.request_hash!=request_hash:raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键用于不同课程修订。")
                return json.loads(replay.result_json)
        checked=preview(service,course_id,path,expected_revision)
        if checked["preview_hash"]!=preview_hash:raise DomainError("PREVIEW_CHANGED","预览后材料或课程发生变化，未发布。","重新预览差异。")
        with service.session() as db:
            course=db.get(Course,course_id)
            old,mapping=existing_content(service,db,course)
            if digest({"old":old,"new":data,"mapping":mapping,"course_id":course_id,"expected_revision":expected_revision})!=preview_hash:raise DomainError("PREVIEW_CHANGED","源内容发生变化。")
            changed=db.execute(update(Course).where(Course.id==course_id,Course.version==expected_revision).values(version=expected_revision+1).execution_options(synchronize_session=False))
            if changed.rowcount!=1:raise DomainError("VERSION_CONFLICT","另一个Agent已发布，未写入。")
            if not db.scalar(select(CourseRevision.id).where(CourseRevision.course_id==course_id,CourseRevision.number==expected_revision)):
                db.add(CourseRevision(id=new_id(),course_id=course_id,number=expected_revision,package_json=json.dumps(old,ensure_ascii=False),mapping_json=json.dumps(mapping),content_hash=digest(old)))
            db.execute(update(Lesson).where(Lesson.course_id==course_id).values(included=False))
            db.execute(update(Exercise).where(Exercise.lesson_id.in_(select(Lesson.id).where(Lesson.course_id==course_id))).values(included=False))
            info_course=data["course"]
            course.title=info_course["title"];course.summary=info_course.get("summary","");course.subject=info_course.get("subject","");course.difficulty=info_course.get("difficulty","")
            for position,source in enumerate(data["lessons"],1):
                lid=mapping["lessons"].get(source["id"])
                lesson=db.get(Lesson,lid) if lid else Lesson(id=new_id(),course_id=course_id)
                lesson.semantic_id=source["id"];lesson.included=True;lesson.title=source["title"];lesson.position=position
                path_relative=f"content/course-revisions/{course_id}/{expected_revision+1}-{info['content_hash']}/{source['id']}.md"
                meta={"content_schema":SCHEMA,"structured_lesson":source,"exercises":source.get("exercises",[])}
                content="---\n"+yaml.safe_dump(meta,allow_unicode=True,sort_keys=False)+"---\n"+fallback_markdown(source)
                target=safe_resolve(service.settings.workspace_root,path_relative);target.parent.mkdir(parents=True,exist_ok=True)
                try:
                    with target.open("x",encoding="utf-8",newline="\n") as stream:stream.write(content)
                except FileExistsError:
                    if target.read_text(encoding="utf-8")!=content:raise DomainError("COURSE_PACKAGE_FILE_CONFLICT","不可变修订文件冲突。")
                lesson.markdown_path=path_relative;db.add(lesson);db.flush();mapping["lessons"][source["id"]]=lesson.id
                for pos,ex in enumerate(source.get("exercises",[]),1):
                    key=source["id"]+":"+ex["id"];eid=mapping["exercises"].get(key)
                    model=db.get(Exercise,eid) if eid else Exercise(id=new_id(),lesson_id=lesson.id)
                    model.semantic_id=ex["id"];model.included=True;model.title=ex["title"];model.prompt=ex["prompt"];model.requirements=ex.get("requirements","");model.position=pos;model.exercise_type=ex.get("type","SHORT_ANSWER");db.add(model);mapping["exercises"][key]=model.id
                inspection=inspect_document(service.settings.workspace_root,path_relative)
                if not db.scalar(select(Document.id).where(Document.relative_path==path_relative)):
                    db.add(Document(id=new_id(),relative_path=path_relative,document_type="LESSON",status=inspection.status,file_size=inspection.file_size,modified_at=inspection.modified_at,content_hash=inspection.content_hash))
            result={"ok":True,"course_id":course_id,"revision":expected_revision+1,"content_hash":info["content_hash"],"historical_rounds_unchanged":True}
            db.add(CourseRevision(id=new_id(),course_id=course_id,number=expected_revision+1,package_json=json.dumps(data,ensure_ascii=False),mapping_json=json.dumps(mapping),content_hash=info["content_hash"],idempotency_key=idempotency_key,request_hash=request_hash,result_json=json.dumps(result)))
            service._event(db,"AGENT_CLI","course",course_id,"PUBLISH_REVISION",f"发布课程修订{expected_revision+1}，活动轮次不变")
            db.flush();return result

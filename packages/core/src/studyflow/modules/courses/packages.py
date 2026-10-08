"""Atomic registration of a whole immutable content package; no direct Agent DB access."""
from __future__ import annotations
from contextlib import contextmanager
import os
import hashlib
import json
from pathlib import Path
import yaml
from sqlalchemy import select
from studyflow.infrastructure.markdown import safe_resolve, inspect_document
from studyflow.modules.courses.content import read_package, fallback_markdown, SCHEMA
from studyflow.modules.courses.models import Course, Lesson, Exercise, CourseRevision
from studyflow.modules.documents.models import Document
from studyflow.modules.planning.models import PlanLine
from studyflow.modules.planning.repository import ensure_course_membership
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE


def inspect_package(path):
    data=read_package(path)
    digest=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    summary={"valid":True,"schema":SCHEMA,"package_id":data["package_id"],"content_hash":digest,"course_title":data["course"]["title"],"plan_line":data["plan_line"],"knowledge_total":len(data["lessons"]),"exercise_total":sum(len(l.get("exercises",[])) for l in data["lessons"]),"block_total":sum(len(l["blocks"]) for l in data["lessons"])}
    return data,summary


@contextmanager
def package_lock(workspace):
    # OS releases the lock on process exit; a failed process cannot leave a stale lock.
    lock_path=workspace/".studyflow"/"course-package.lock"
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0,2)
        if handle.tell()==0: handle.write(b"0");handle.flush()
        handle.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise DomainError("COURSE_PACKAGE_BUSY","另一个进程正在发布课程。","稍后使用同一课程包重试，不要更改package_id。") from exc
        try: yield
        finally:
            handle.seek(0)
            if os.name=="nt": msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def import_package(service,path):
    # Validation remains read-only and occurs before acquiring publication resources.
    data,summary=inspect_package(path)
    with package_lock(service.settings.workspace_root):
        return _import_package(service,data,summary)


def _import_package(service,data,summary):
    base=f"content/course-packages/{data['package_id']}/"
    folder=base+summary['content_hash']+"/"
    expected=[folder+lesson['id']+".md" for lesson in data['lessons']]
    with service.session() as db:
        revisions=db.scalars(select(CourseRevision)).all()
        for revision in revisions:
            stored=json.loads(revision.package_json)
            if stored.get("package_id")==data["package_id"]:
                if revision.content_hash==summary["content_hash"]:
                    return {**summary,"created":False,"course_id":revision.course_id,"revision":revision.number,"lesson_ids":list(json.loads(revision.mapping_json)["lessons"].values())}
                # A known package identity cannot become another course.
                if not any(r.content_hash==summary["content_hash"] for r in revisions if r.course_id==revision.course_id):
                    raise DomainError("COURSE_PACKAGE_CONFLICT","package_id已属于既有课程，不能导入不同内容。","使用显式修订预览与发布，不创建重复课程。")
        # Package ids are stable across titles. Never silently mutate a learner's material.
        registered=db.scalars(select(Lesson).where(Lesson.markdown_path.startswith(base,autoescape=True))).all()
        if registered:
            if {l.markdown_path for l in registered}!=set(expected):
                raise DomainError("COURSE_PACKAGE_CONFLICT","此package_id已登记不同内容。","使用course.update.preview/apply显式修订既有课程；旧轮次不会被替换。")
            if len({l.course_id for l in registered})!=1:raise DomainError("COURSE_PACKAGE_CONFLICT","课程包登记不完整。","保留数据并检查工作区。")
            return {**summary,"created":False,"course_id":registered[0].course_id,"lesson_ids":[next(l.id for l in registered if l.markdown_path==p) for p in expected]}
        plan=db.scalar(select(PlanLine).where(PlanLine.name==data['plan_line']))
        if not plan:raise DomainError("PLAN_LINE_NOT_FOUND","计划不存在。","先用 plan create 创建课程包指定的计划。")
        if db.scalar(select(Course).where(Course.plan_line_id==plan.id,Course.title==data['course']['title'])):
            raise DomainError("COURSE_ALREADY_EXISTS","同计划中已有同名课程，未追加或覆盖。","新版本使用明确的新课程标题；旧课程及答案保留。")
        info=data['course']
        course=Course(id=new_id(),plan_line_id=plan.id,title=info['title'],summary=info.get('summary',''),subject=info.get('subject',''),difficulty=info.get('difficulty',''),source_type=AGENT_SOURCE)
        db.add(course);db.flush()
        membership=ensure_course_membership(db,plan,course)
        ids=[]
        mapping={"lessons":{},"exercises":{}}
        for index,(source,relative) in enumerate(zip(data['lessons'],expected),1):
            metadata={'course':info['title'],'lesson':source['title'],'plan_line':data['plan_line'],'summary':info.get('summary',''),'content_schema':SCHEMA,'package_id':data['package_id'],'package_hash':summary['content_hash'],'structured_lesson':source,'exercises':source.get('exercises',[])}
            content='---\n'+yaml.safe_dump(metadata,allow_unicode=True,sort_keys=False)+'---\n'+fallback_markdown(source)
            target=safe_resolve(service.settings.workspace_root,relative)
            target.parent.mkdir(parents=True,exist_ok=True)
            try:
                with target.open('x',encoding='utf-8',newline='\n') as f:f.write(content)
            except FileExistsError:
                if target.read_text(encoding='utf-8')!=content:raise DomainError("COURSE_PACKAGE_FILE_CONFLICT","课程包目标文件与预期不同，未覆盖。","检查原文件；不要自动删除或覆盖。")
            lesson=Lesson(id=new_id(),semantic_id=source["id"],course_id=course.id,title=source['title'],position=index,markdown_path=relative,summary='')
            for pos,ex in enumerate(source.get('exercises',[]),1):
                lesson.exercises.append(Exercise(id=new_id(),semantic_id=ex["id"],title=ex['title'],prompt=ex['prompt'],requirements=ex.get('requirements',''),exercise_type=ex.get('type','SHORT_ANSWER'),position=pos))
            db.add(lesson);ids.append(lesson.id)
            mapping["lessons"][source["id"]]=lesson.id
            for ex,model in zip(source.get("exercises",[]),lesson.exercises):mapping["exercises"][source["id"]+":"+ex["id"]]=model.id
            inspection=inspect_document(service.settings.workspace_root,relative)
            db.add(Document(id=new_id(),relative_path=relative,document_type='LESSON',status=inspection.status,file_size=inspection.file_size,modified_at=inspection.modified_at,content_hash=inspection.content_hash))
        db.flush()
        db.add(CourseRevision(id=new_id(),course_id=course.id,number=1,package_json=json.dumps(data,ensure_ascii=False),mapping_json=json.dumps(mapping),content_hash=summary["content_hash"]))
        service._event(db,AGENT_SOURCE,'course',course.id,'IMPORT_PACKAGE',data['package_id'])
        return {**summary,'created':True,'course_id':course.id,'plan_id':plan.id,'plan_course_item_id':membership.id,'lesson_ids':ids,'paths':expected}

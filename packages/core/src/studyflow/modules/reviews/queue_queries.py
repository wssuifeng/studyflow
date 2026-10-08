"""Paged work projections and deduplicated, on-demand Agent context."""
import json
from sqlalchemy import select, func, exists
from sqlalchemy.orm import aliased, joinedload, selectinload, load_only
from studyflow.modules.learning.models import Submission, CourseStudySession
from studyflow.modules.courses.models import Course, Exercise, Lesson
from studyflow.shared.domain import DomainError
from .models import RetestTask

STATES={"WAITING_REVIEW","NEEDS_REVISION","RETEST_REQUIRED","PASSED","REVIEWED","RECHECKED"}
def summary(service, role="all", plan_line_id=None, course_id=None, status=None, cursor=None, limit=50, history=False):
    if role not in {"agent","learner","all"} or isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100 or status and status not in STATES:
        raise DomainError("INVALID_ARGUMENT","队列role/status/limit不正确，limit范围1—100。")
    child=aliased(Submission)
    query=select(Submission).join(Exercise).join(Lesson).join(Course).where(Submission.status.in_(STATES),~exists(select(child.id).where(child.parent_submission_id==Submission.id,child.status!="DRAFT")))
    if plan_line_id:query=query.where(Course.plan_line_id==plan_line_id)
    if course_id:query=query.where(Course.id==course_id)
    if history:query=query.where(Submission.status.in_({"PASSED","REVIEWED","RECHECKED"}))
    else:query=query.where(Submission.status.in_({"WAITING_REVIEW","NEEDS_REVISION","RETEST_REQUIRED"}))
    if status:query=query.where(Submission.status==status)
    task_exists=exists(select(RetestTask.id).where(RetestTask.parent_submission_id==Submission.id))
    if role=="agent":query=query.where((Submission.status=="WAITING_REVIEW")|((Submission.status=="RETEST_REQUIRED")&~task_exists))
    if role=="learner":query=query.where((Submission.status=="NEEDS_REVISION")|((Submission.status=="RETEST_REQUIRED")&task_exists))
    with service.session() as db:
        from studyflow.modules.learning.write_contract import effective_rows
        active={r.id for r in effective_rows(db,list(db.scalars(select(Submission).options(load_only(Submission.id,Submission.parent_submission_id)))))}
        query=query.where(Submission.id.in_(active))
        counts=dict(db.execute(select(Submission.status,func.count()).where(Submission.id.in_(query.with_only_columns(Submission.id))).group_by(Submission.status)).all())
        if cursor:
            if not isinstance(cursor,str) or len(cursor)>64:raise DomainError("INVALID_ARGUMENT","cursor必须是返回的游标。")
            query=query.where(Submission.id>cursor)
        rows=db.scalars(query.options(
            load_only(Submission.id, Submission.status, Submission.version, Submission.exercise_id,
                      Submission.study_session_id, Submission.batch_id, Submission.attempt_number,
                      Submission.attempt_kind, Submission.next_action),
            joinedload(Submission.exercise).load_only(Exercise.id, Exercise.lesson_id, Exercise.title)
                .joinedload(Exercise.lesson).load_only(Lesson.id, Lesson.course_id, Lesson.title)
                .joinedload(Lesson.course).load_only(Course.id, Course.plan_line_id, Course.title),
            selectinload(Submission.study_session).load_only(CourseStudySession.id, CourseStudySession.snapshot_json),
        ).order_by(Submission.id).limit(limit+1)).unique().all()
        tasks=set(db.scalars(select(RetestTask.parent_submission_id)
                            .where(RetestTask.parent_submission_id.in_([r.id for r in rows[:limit]]))))
        # Fetch and parse each frozen round once; summaries never load answer bodies or rubrics.
        frozen_titles={}
        for row in rows[:limit]:
            study=row.study_session
            if study and study.id not in frozen_titles:
                snapshot=json.loads(study.snapshot_json)
                frozen_titles[study.id]={exercise["id"]: {
                    "course_title": snapshot["course"]["title"],
                    "lesson_title": lesson["title"], "exercise_title": exercise["title"]
                } for lesson in snapshot["lessons"] for exercise in lesson["exercises"]}
        items=[]
        for row in rows[:limit]:
            course=row.exercise.lesson.course
            task=row.id in tasks
            action="REVIEW" if row.status=="WAITING_REVIEW" else "REVISE" if row.status=="NEEDS_REVISION" else "RETEST" if task else "PUBLISH_RETEST" if row.status=="RETEST_REQUIRED" else "VIEW_HISTORY"
            items.append({"id":row.id,"status":row.status,"version":row.version,"action":action,"kind":action,"label":{"REVIEW":"等待Agent批改","REVISE":"需要修正","RETEST":"开始复测","PUBLISH_RETEST":"等待Agent出题","VIEW_HISTORY":"已通过历史"}[action],"course_id":course.id,"course_title":course.title,"plan_line_id":course.plan_line_id,"lesson_id":row.exercise.lesson_id,"lesson_title":row.exercise.lesson.title,"exercise_id":row.exercise_id,"exercise_title":row.exercise.title,"study_session_id":row.study_session_id,"batch_id":row.batch_id,"attempt_number":row.attempt_number,"attempt_kind":row.attempt_kind,"next_action":row.next_action})
            frozen=frozen_titles.get(row.study_session_id,{}).get(row.exercise_id)
            if frozen:items[-1].update(frozen)
        return {"items":items,"counts":counts,"next_cursor":rows[limit-1].id if len(rows)>limit else None,"limit":limit,"role":role}

def context(service, submission_ids):
    if not isinstance(submission_ids,list) or not 1<=len(submission_ids)<=100 or any(not isinstance(i,str) for i in submission_ids):raise DomainError("INVALID_ARGUMENT","submission_ids需要1—100个ID。")
    contexts,items={},[]
    for identifier in dict.fromkeys(submission_ids):
        detail=service.submission_detail(identifier)
        frozen=detail.pop("study_context",None)
        context_id=(frozen["study_session_id"]+":"+frozen["lesson"]["id"]) if frozen else "legacy:"+detail["lesson"]["id"]
        if context_id not in contexts:
            contexts[context_id]={k:v for k,v in frozen.items() if k!="exercise"} if frozen else {"snapshot_status":"LEGACY_UNVERSIONED","lesson":detail["lesson"],"course":detail["course"]}
        with service.session() as db:
            task=db.get(RetestTask,detail.get("retest_task_id")) if detail.get("retest_task_id") else None
            if task:detail["agent_reference"]=task.agent_reference
        items.append({"context_id":context_id,**detail})
    return {"items":items,"contexts":contexts}

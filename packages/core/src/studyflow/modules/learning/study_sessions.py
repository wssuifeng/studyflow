"""Local course rounds: immutable teaching context, recoverable reading, derived outcome."""
from __future__ import annotations
import hashlib
import json
from sqlalchemy import func, or_, select, update
from studyflow.infrastructure.markdown import safe_resolve
from studyflow.modules.learning.models import CourseStudySession, CourseWriteReceipt, LearningProgress, Submission
from studyflow.shared.constants import PASSED_STATES
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id


def current_study(db, course_id):
    return db.scalar(select(CourseStudySession).where(CourseStudySession.course_id == course_id)
                     .order_by(CourseStudySession.revision.desc()))


def require_study(db, identifier, course_id=None, active=False):
    if not isinstance(identifier,str) or not identifier.strip():
        raise DomainError("INVALID_ARGUMENT", "学习会话ID必须是非空文本。")
    row = db.get(CourseStudySession, identifier)
    if not row or (course_id and row.course_id != course_id):
        raise DomainError("OBJECT_NOT_FOUND", "学习会话不存在或不属于本课。", "重新打开课程，保留本机未保存内容。")
    if active and current_study(db, row.course_id).id != row.id:
        raise DomainError("VERSION_CONFLICT", "该轮学习已经收口，当前课程正在使用另一个版本。", "保留草稿并重新打开当前学习轮次。")
    return row


def exercise_ids(study):
    return [ex["id"] for lesson in json.loads(study.snapshot_json)["lessons"] for ex in lesson["exercises"]]


def study_scope(study):
    return or_(Submission.study_session_id == study.id, Submission.study_session_id.is_(None)) if study.revision == 1 else Submission.study_session_id == study.id


def study_attempts(db, study, include_drafts=False):
    query = select(Submission).where(Submission.exercise_id.in_(exercise_ids(study)), study_scope(study))
    if not include_drafts: query = query.where(Submission.status != "DRAFT")
    rows = db.scalars(query.order_by(Submission.attempt_number, Submission.created_at, Submission.id)).all()
    from .write_contract import effective_rows
    return {row.exercise_id: row for row in effective_rows(db, rows)}


def outcome(db, study):
    ids = exercise_ids(study)
    latest = study_attempts(db, study)
    states = [latest[eid].status if eid in latest else "NOT_SUBMITTED" for eid in ids]
    waiting = sum(status == "WAITING_REVIEW" for status in states)
    passed = sum(status in PASSED_STATES for status in states)
    feedback = sum(status != "NOT_SUBMITTED" and status != "WAITING_REVIEW" for status in states)
    if not ids:
        status = "READ_COMPLETED" if study.reading_completed else "IN_PROGRESS"
    elif "NEEDS_REVISION" in states: status = "NEEDS_REVISION"
    elif "RETEST_REQUIRED" in states: status = "RETEST_REQUIRED"
    elif passed == len(ids): status = "PASSED"
    elif "NOT_SUBMITTED" in states: status = "IN_PROGRESS"
    elif waiting == len(ids): status = "WAITING_REVIEW"
    else: status = "PARTIAL_FEEDBACK"
    batches = [row.batch_id for row in latest.values() if row.batch_id]
    return {"study_status": status, "exercise_total": len(ids), "exercise_completed": passed,
            "waiting_count": waiting, "feedback_count": feedback, "batch_id": batches[-1] if batches else None,
            "learning_submitted": bool(ids) and "NOT_SUBMITTED" not in states or not ids and study.reading_completed}


def capture(service, course_id):
    from studyflow.modules.courses.service import CoursesService
    data = CoursesService(service.runtime).course_detail(course_id)
    course = {key: data["course"].get(key) for key in ("id", "title", "summary", "subject", "content_type", "difficulty", "source_type", "plan_line", "plan_line_id", "status")}
    lessons = []
    if not data["lessons"]:
        raise DomainError("EMPTY_COURSE", "本课尚未准备知识点。", "请外部Agent导入学习材料后再开始。")
    for source in data["lessons"]:
        if source["document_status"] != "PRESENT":
            raise DomainError("DOCUMENT_UNREADABLE", "学习材料暂时无法读取，未开始新学习轮次。", "修复材料后重试；已有会话可继续使用冻结材料。")
        lesson = {key: source[key] for key in ("id", "title", "position", "markdown_path", "summary", "document_status", "rendered_html")}
        try:
            markdown = safe_resolve(service.settings.workspace_root, source["markdown_path"]).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DomainError("DOCUMENT_UNREADABLE", "学习材料无法读取。", "确认材料是可读UTF-8文件。") from exc
        # Render and hash the same read, not a second potentially changing file version.
        from studyflow.infrastructure.markdown import render_markdown, parse_front_matter
        body = parse_front_matter(markdown)[1] if markdown.startswith(("---\n", "---\r\n")) else markdown
        lesson["markdown"] = markdown
        lesson["rendered_html"] = render_markdown(body)
        from studyflow.modules.courses.content import render_blocks
        blocks = render_blocks(markdown, [ex["id"] for ex in source["exercises"]]) if markdown.startswith(("---\n", "---\r\n")) else []
        if blocks: lesson["content_blocks"] = blocks
        lesson["exercises"] = [{key: ex[key] for key in ("id", "title", "prompt", "requirements", "type", "position")} for ex in source["exercises"]]
        lessons.append(lesson)
    content = {"course": course, "lessons": lessons}
    text = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def detail(service, study_id):
    with service.session() as db:
        study = require_study(db, study_id)
        content = json.loads(study.snapshot_json)
        progress = json.loads(study.progress_json)
        latest = study_attempts(db, study)
        all_rows = study_attempts(db, study, include_drafts=True)
        for lesson in content["lessons"]:
            lesson["progress"] = progress.get(lesson["id"], {"progress_percent": 0, "status": "NOT_STARTED", "last_position": ""})
            for ex in lesson["exercises"]:
                from studyflow.modules.learning.presentation import submission_summary
                ex["latest_submission"] = submission_summary(latest[ex["id"]]) if ex["id"] in latest else None
                draft = all_rows.get(ex["id"])
                ex["draft"] = submission_summary(draft) if draft and draft.status == "DRAFT" else None
        course = content["course"]
        course.update(outcome(db, study))
        course["knowledge_total"] = len(content["lessons"])
        course["knowledge_completed"] = sum(l["progress"]["status"] == "COMPLETED" for l in content["lessons"])
        course["reading_percent"] = round(sum(l["progress"]["progress_percent"] for l in content["lessons"]) / len(content["lessons"]))
        course["progress_percent"] = round(course["exercise_completed"] / course["exercise_total"] * 100) if course["exercise_total"] else course["reading_percent"]
        from studyflow.modules.planning.models import PlanCourseItem
        membership = db.scalar(select(PlanCourseItem).where(PlanCourseItem.course_id == study.course_id).order_by(PlanCourseItem.sequence_number))
        course["sequence"] = membership.sequence_number if membership else None
        course["total"] = db.scalar(select(func.count(PlanCourseItem.id)).where(PlanCourseItem.plan_line_id == membership.plan_line_id)) if membership else 0
        version = {"id":study.id,"revision":study.revision,"content_hash":study.content_hash,"progress_version":study.version,
                   "source_changed":False,"source_available":True,"is_current":current_study(db,study.course_id).id == study.id}
        try: version["source_changed"] = capture(service, study.course_id)[1] != study.content_hash
        except DomainError: version.update(source_available=False, source_changed=True)
        return {"course": course, "lessons": content["lessons"], "study": version,
                "resume_lesson_id": study.resume_lesson_id, "next_action":"在当前知识点学习和作答，整课完成后统一提交。"}


def open_study(service, course_id, key, new_version=False, review_round=False):
    if not isinstance(key,str) or not key.strip() or len(key)>160 or not isinstance(new_version,bool) or not isinstance(review_round,bool):
        raise DomainError("INVALID_ARGUMENT", "学习开始需要有效幂等键和布尔new_version。", "同一请求使用原幂等键。")
    with service.session() as db:
        request_payload={"course_id":course_id,"new_version":new_version}
        if review_round: request_payload["review_round"]=True
        digest_request=hashlib.sha256(json.dumps(request_payload,sort_keys=True).encode()).hexdigest()
        receipt = db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==key))
        replay = db.scalar(select(CourseStudySession).where(CourseStudySession.idempotency_key == key))
        if receipt:
            if receipt.operation!="STUDY_OPEN" or receipt.payload_hash!=digest_request:
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已用于其他学习写入请求。")
            identifier=json.loads(receipt.result_json)["study_session_id"]
        elif replay:
            if replay.course_id != course_id or replay.new_version != (new_version or review_round):
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他学习开始请求。")
            identifier = replay.id
        else:
            current = current_study(db, course_id)
            if current and not new_version and not review_round:
                identifier = current.id
            else:
                if current and outcome(db,current)["study_status"] not in {"PASSED","READ_COMPLETED"}:
                    raise DomainError("COURSE_STUDY_IN_PROGRESS", "当前学习尚未收口，不能切换材料版本。", "完成当前作答与反馈后，再开始新版学习。")
                text, digest = capture(service, course_id)
                if current and digest == current.content_hash and not review_round:
                    raise DomainError("COURSE_VERSION_UNCHANGED", "学习材料没有更新，无需开始新版。", "继续回看当前课程即可。")
                progress = {}
                if not current:
                    for row in db.scalars(select(LearningProgress).where(LearningProgress.course_id == course_id)):
                        progress[row.lesson_id] = {"progress_percent":row.progress_percent,"status":row.status,"last_position":row.last_position}
                row = CourseStudySession(id=new_id(), course_id=course_id, revision=current.revision+1 if current else 1,
                    idempotency_key=key, new_version=new_version or review_round, snapshot_json=text, content_hash=digest,
                    progress_json=json.dumps(progress), version=1)
                db.add(row); db.flush(); identifier=row.id
                service._event(db,"USER_ENGINE","course_study",row.id,"OPEN","开始固定版本的本地学习轮次")
        if not receipt:
            db.add(CourseWriteReceipt(id=new_id(),idempotency_key=key,course_id=course_id,study_session_id=identifier,
                operation="STUDY_OPEN",payload_hash=digest_request,result_json=json.dumps({"study_session_id":identifier})))
            db.flush()
    return detail(service,identifier)


def save_progress(service, study_id, lesson_id, percent, position, expected_version=None):
    if isinstance(percent,bool) or not isinstance(percent,int) or not 0<=percent<=100 or not isinstance(position,str):
        raise DomainError("INVALID_ARGUMENT", "阅读进度必须是0—100整数，位置必须是文本。")
    with service.session() as db:
        row = require_study(db,study_id,active=True)
        if lesson_id not in {l["id"] for l in json.loads(row.snapshot_json)["lessons"]}:
            raise DomainError("INVALID_ARGUMENT", "知识点不属于当前学习版本。")
        if expected_version is not None and (isinstance(expected_version,bool) or not isinstance(expected_version,int) or expected_version != row.version):
            raise DomainError("VERSION_CONFLICT", "阅读位置已被其他窗口更新。", "保留答案并重新读取课程。")
        progress = json.loads(row.progress_json)
        previous = progress.get(lesson_id,{})
        percent = max(percent, previous.get("progress_percent",0))
        value = {"progress_percent":percent,"status":"COMPLETED" if percent==100 else "IN_PROGRESS" if percent else "NOT_STARTED","last_position":position[:500]}
        progress[lesson_id]=value
        version=row.version
        changed=db.execute(update(CourseStudySession).where(CourseStudySession.id==row.id,CourseStudySession.version==version)
            .values(progress_json=json.dumps(progress),resume_lesson_id=lesson_id,version=version+1).execution_options(synchronize_session=False))
        if changed.rowcount!=1: raise DomainError("VERSION_CONFLICT","阅读位置版本冲突，请重新读取。")
        return {"id":row.id,"study_session_id":row.id,"course_id":row.course_id,"lesson_id":lesson_id,"version":version+1,**value}


def complete_reading(service, study_id):
    with service.session() as db:
        row=require_study(db,study_id,active=True)
        progress=json.loads(row.progress_json)
        lessons=json.loads(row.snapshot_json)["lessons"]
        if exercise_ids(row) or any(progress.get(l["id"],{}).get("progress_percent")!=100 for l in lessons):
            raise DomainError("READING_INCOMPLETE","仅无练习且已确认读完全部知识点的课程可完成阅读。","确认所有知识点；有练习的课程应整课提交。")
        row.reading_completed=True
        db.flush()
    return detail(service,study_id)


def frozen_context(row):
    session=row.study_session
    if not session: return None
    content=json.loads(session.snapshot_json)
    for lesson in content["lessons"]:
        for ex in lesson["exercises"]:
            if ex["id"]==row.exercise_id:
                return {"study_session_id":session.id,"revision":session.revision,"content_hash":session.content_hash,
                        "course":content["course"],"lesson":{k:v for k,v in lesson.items() if k not in {"exercises","markdown","rendered_html"}},
                        "exercise":ex,"markdown":lesson["markdown"]}
    return None


def bind_submission(db, row, is_new=False):
    """Keep legacy single-question adapters in the same local round as whole-course writes."""
    from studyflow.modules.courses.models import Exercise
    exercise=db.get(Exercise,row.exercise_id)
    study=current_study(db,exercise.lesson.course_id) if exercise else None
    if not study: return
    if row.exercise_id not in exercise_ids(study):
        raise DomainError("VERSION_CONFLICT","本题不属于当前固定学习版本。","在新版开始后再处理新增题目。")
    if row.study_session_id and row.study_session_id != study.id or not row.study_session_id and not is_new and study.revision>1:
        raise DomainError("VERSION_CONFLICT","作答属于已经收口的学习轮次。","读取当前课程，不修改旧轮次原答案。")
    if row.parent_submission_id:
        parent=db.get(Submission,row.parent_submission_id)
        if parent and (parent.study_session_id not in ({None,study.id} if study.revision==1 else {study.id})):
            raise DomainError("VERSION_CONFLICT","后续作答的父记录属于旧轮次。","按当前轮次反馈进行修正或复测。")
    elif is_new:
        formal=study_attempts(db,study).get(row.exercise_id)
        if formal:
            raise DomainError("INVALID_STATE_TRANSITION","本轮已有正式作答，不能创建另一份首次答案。","按反馈使用修正或复测入口。")
    row.study_session_id=study.id

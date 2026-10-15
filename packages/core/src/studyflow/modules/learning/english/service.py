"""English operations use a caller-owned Session; no independent commit."""
import json
from sqlalchemy import select, update, func
from studyflow.modules.learning.models import Submission
from studyflow.modules.learning.study_sessions import require_study
from studyflow.modules.learning.english.models import EnglishStudyState, EnglishSubmissionDetail, EnglishCheckAttempt
from studyflow.modules.learning.english.checker import check_answer, tokenize, rule_hash
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id


def context(db, study_id, exercise_id=None, active=False):
    study=require_study(db,study_id,active=active)
    frozen=json.loads(study.snapshot_json)
    if frozen["course"].get("learning_mode")!="english":
        raise DomainError("COURSE_MODE_MISMATCH","此轮不是英语训练。")
    items=[{**ex,"lesson_id":lesson["id"],"group_title":lesson["title"]} for lesson in frozen["lessons"] for ex in lesson["exercises"]]
    if exercise_id is None:return study,frozen,items
    item=next((x for x in items if x["id"]==exercise_id),None)
    if not item:raise DomainError("OBJECT_NOT_FOUND","训练项不属于本轮冻结课程。")
    return study,frozen,item


def state(db,study,frozen,create=False):
    row=db.get(EnglishStudyState,study.id)
    if row is None and create:
        row=EnglishStudyState(study_session_id=study.id,plan_line_id=frozen["course"].get("plan_line_id"),position=0,version=1,completed=False)
        db.add(row);db.flush()
    return row


def latest(db,study_id,exercise_id):
    return db.scalar(select(Submission).where(Submission.study_session_id==study_id,Submission.exercise_id==exercise_id,Submission.retest_task_id.is_(None)).order_by(Submission.attempt_number.desc(),Submission.created_at.desc(),Submission.id.desc()))


def consecutive_errors(db,study_id,exercise_id):
    count=0
    attempts=db.scalars(select(EnglishCheckAttempt).where(EnglishCheckAttempt.study_session_id==study_id,EnglishCheckAttempt.exercise_id==exercise_id,EnglishCheckAttempt.retest_task_id.is_(None)).order_by(EnglishCheckAttempt.created_at.desc(),EnglishCheckAttempt.id.desc()))
    for attempt in attempts:
        matched=json.loads(attempt.result_json).get("matched")
        if matched:break
        if matched is False:count+=1
    return count


def get_view(db,study_id):
    study,frozen,items=context(db,study_id)
    session=state(db,study,frozen)
    result=[]
    for ex in items:
        row=latest(db,study_id,ex["id"])
        detail=db.get(EnglishSubmissionDetail,row.id) if row else None
        attempt=db.get(EnglishCheckAttempt,detail.last_attempt_id) if detail and detail.last_attempt_id else None
        checked=json.loads(attempt.result_json) if attempt else {}
        result.append({"exercise_id":ex["id"],"lesson_id":ex["lesson_id"],"title":ex["title"],"prompt":ex["prompt"],"group_title":ex["group_title"],"progression":ex["english"].get("progression"),"token_count":len(tokenize(ex["english"]["target"])),"min_token_count":min(len(tokenize(x)) for x in [ex["english"]["target"],*ex["english"].get("accepted_answers",[])]),"max_token_count":max(len(tokenize(x)) for x in [ex["english"]["target"],*ex["english"].get("accepted_answers",[])]),"error_count":checked.get("error_count",0),"evaluation_mode":ex["english"].get("evaluation_mode","local_exact"),"objective_ids":ex["english"].get("objective_ids",[]),"answer_text":row.answer_text if row else "","answer_version":row.version if row else 0,"submission_id":row.id if row else None,"status":row.status if row else "NOT_STARTED","matched":checked.get("matched",False),"differences":checked.get("differences",[]),"assisted":bool(detail and detail.assisted),"skipped":bool(detail and detail.skipped)})
    course=dict(frozen["course"])
    from studyflow.modules.courses.models import Course
    live=db.get(Course,study.course_id)
    course["source_changed"]=bool(live and frozen["course"].get("content_revision") and live.version!=frozen["course"]["content_revision"])
    return {"content_hash":study.content_hash,"course":course,"study_session_id":study_id,"revision":study.revision,"position":session.position if session else 0,"state_version":session.version if session else 0,"completed":bool(session and session.completed),"items":result,"groups":[{"lesson_id":l["id"],"title":l["title"],"summary":l.get("summary",""),"blocks":l.get("content_blocks",[])} for l in frozen["lessons"]]}


def save(db,study_id,exercise_id,answer_text,expected_version,skipped=False):
    study,frozen,item=context(db,study_id,exercise_id,active=True)
    if not isinstance(answer_text,str) or len(answer_text)>4000 or isinstance(expected_version,bool) or not isinstance(expected_version,int) or expected_version<0:
        raise DomainError("INVALID_ARGUMENT","答案必须是最多4000字符的文本，版本必须为非负整数。")
    row=latest(db,study_id,exercise_id)
    current_version=row.version if row else 0
    if current_version!=expected_version:raise DomainError("VERSION_CONFLICT","答案已变化，未覆盖另一窗口。","回读当前版本并保留本机输入。")
    if row and row.status=="WAITING_REVIEW":raise DomainError("ANSWER_LOCKED","此项正在等待Agent审核。")
    if row and row.status in {"PASSED","RECHECKED","REVIEWED"}:raise DomainError("ANSWER_LOCKED","正式通过的原答案不可覆盖，请开始回顾轮次。")
    if row and row.status!="DRAFT":
        parent=row
        row=Submission(id=new_id(),exercise_id=exercise_id,study_session_id=study_id,parent_submission_id=parent.id,attempt_number=parent.attempt_number+1,attempt_kind="REVISION",answer_text=answer_text,status="DRAFT",version=1,source="USER_ENGINE")
        from studyflow.modules.learning.write_contract import claim_parent
        claim_parent(db,parent,row.id,"USER_ENGINE");db.add(row)
    elif row:
        changed=db.execute(update(Submission).where(Submission.id==row.id,Submission.version==expected_version,Submission.status=="DRAFT").values(answer_text=answer_text,version=expected_version+1).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise DomainError("VERSION_CONFLICT","草稿版本冲突。")
        db.expire(row);db.refresh(row)
    else:
        row=Submission(id=new_id(),exercise_id=exercise_id,study_session_id=study_id,answer_text=answer_text,status="DRAFT",version=1,attempt_number=1,attempt_kind="FIRST",source="USER_ENGINE")
        db.add(row)
    db.flush()
    detail=db.get(EnglishSubmissionDetail,row.id) or EnglishSubmissionDetail(submission_id=row.id)
    detail.last_attempt_id=None;detail.skipped=skipped;detail.evaluation_mode=item["english"].get("evaluation_mode","local_exact")
    db.add(detail);session=state(db,study,frozen,True);session.completed=False;session.version+=1;db.flush()
    return {"submission_id":row.id,"answer_version":row.version,"state_version":session.version,"saved":True}


def check(db,study_id,exercise_id,expected_version):
    study,frozen,item=context(db,study_id,exercise_id,active=True)
    row=latest(db,study_id,exercise_id)
    if not row or row.status!="DRAFT" or row.version!=expected_version:raise DomainError("VERSION_CONFLICT","需要当前可编辑答案版本才能检查。")
    if not row.answer_text.strip():raise DomainError("ANSWER_EMPTY","先输入答案；跳过不算答错。")
    detail=db.get(EnglishSubmissionDetail,row.id)
    result=check_answer(item["english"],row.answer_text)
    result["error_count"]=0 if result["matched"] else consecutive_errors(db,study_id,exercise_id)+1
    attempt=EnglishCheckAttempt(id=new_id(),study_session_id=study_id,exercise_id=exercise_id,submission_id=row.id,answer_text=row.answer_text,answer_version=row.version,rule_hash=rule_hash(item["english"],item["prompt"]),result_json=json.dumps(result,ensure_ascii=False),assisted=detail.assisted)
    db.add(attempt);db.flush();detail.last_attempt_id=attempt.id;detail.skipped=False
    session=state(db,study,frozen,True);session.version+=1
    return {**result,"attempt_id":attempt.id,"answer_version":row.version,"state_version":session.version},(study,frozen,item,attempt)


def reveal(db,study_id,exercise_id):
    study,frozen,item=context(db,study_id,exercise_id,active=True)
    row=latest(db,study_id,exercise_id)
    if row:
        detail=db.get(EnglishSubmissionDetail,row.id)
        detail.assisted=True
    else:
        save(db,study_id,exercise_id,"",0)
        row=latest(db,study_id,exercise_id);db.get(EnglishSubmissionDetail,row.id).assisted=True
    session=state(db,study,frozen,True);session.version+=1
    spec=item["english"]
    return {"target":spec["target"],"tokens":tokenize(spec["target"]),"phonetic":spec.get("phonetic",""),"gloss":spec.get("gloss",""),"explanation":spec.get("explanation",""),"sentence_parts":spec.get("sentence_parts",[]),"assisted":True,"answer_version":row.version,"state_version":session.version}


def answer_view(db,study_id,exercise_id):
    _,_,item=context(db,study_id,exercise_id)
    row=latest(db,study_id,exercise_id)
    detail=db.get(EnglishSubmissionDetail,row.id) if row else None
    attempt=db.get(EnglishCheckAttempt,detail.last_attempt_id) if detail and detail.last_attempt_id else None
    if not (row and row.status in {"PASSED","RECHECKED","REVIEWED"}) and not (detail and detail.assisted) and not (attempt and json.loads(attempt.result_json).get("matched")):
        raise DomainError("REFERENCE_HIDDEN","请先检查通过或显式查看答案。")
    spec=item["english"]
    return {"target":spec["target"],"tokens":tokenize(spec["target"]),"phonetic":spec.get("phonetic",""),"gloss":spec.get("gloss",""),"explanation":spec.get("explanation",""),"sentence_parts":spec.get("sentence_parts",[])}


def submit(db,study_id,expected_versions=None):
    study,frozen,items=context(db,study_id,active=True)
    if expected_versions is not None and set(expected_versions)!={item["id"] for item in items}:raise DomainError("INVALID_ARGUMENT","提交版本映射必须恰好覆盖本轮全部训练项。")
    rows=[];missing=[]
    for item in items:
        row=latest(db,study_id,item["id"])
        if expected_versions is not None and expected_versions.get(item["id"])!=(row.version if row else 0):raise DomainError("VERSION_CONFLICT","提交前答案版本变化，整课未提交。")
        if row and row.status in {"WAITING_REVIEW","PASSED","RECHECKED","REVIEWED"}:continue
        detail=db.get(EnglishSubmissionDetail,row.id) if row else None
        attempt=db.get(EnglishCheckAttempt,detail.last_attempt_id) if detail and detail.last_attempt_id else None
        matched=bool(attempt and json.loads(attempt.result_json).get("matched"))
        agent=False
        if not row or detail.skipped or not row.answer_text.strip() or not (matched or agent):missing.append(item["id"])
        else:rows.append((row,agent))
    if missing:raise DomainError("COURSE_INCOMPLETE","还有未完成或未有效检查的训练项。","返回这些项："+",".join(missing))
    batch=new_id()
    for row,agent in rows:
        row.status="WAITING_REVIEW" if agent else "RECHECKED" if row.parent_submission_id else "PASSED"
        row.version+=1;row.batch_id=batch;row.next_action="等待Agent审核。" if agent else "本地规则检查通过，不代表长期掌握。"
    session=state(db,study,frozen,True);session.completed=True;session.version+=1
    waiting=sum(latest(db,study_id,item["id"]).status=="WAITING_REVIEW" for item in items)
    return {"completed":True,"waiting_review":waiting,"batch_id":batch,"state_version":session.version}


def request_review(db,study_id,exercise_id,expected_version):
    context(db,study_id,exercise_id,active=True)
    row=latest(db,study_id,exercise_id)
    if not row or row.status!="DRAFT" or row.version!=expected_version:raise DomainError("VERSION_CONFLICT","审核必须引用当前草稿版本。")
    if not row.answer_text.strip():raise DomainError("ANSWER_EMPTY","不能审核空答案。")
    detail=db.get(EnglishSubmissionDetail,row.id);detail.evaluation_mode="agent"
    row.status="WAITING_REVIEW";row.version+=1;row.next_action="等待Agent审核此项；其余项可以继续。"
    return {"submission_id":row.id,"answer_version":row.version,"status":row.status}


def navigate(db,study_id,position,expected_version):
    study,frozen,items=context(db,study_id,active=True)
    current=state(db,study,frozen)
    if expected_version!=(current.version if current else 0):raise DomainError("VERSION_CONFLICT","学习位置版本冲突。")
    if isinstance(position,bool) or not isinstance(position,int) or not 0<=position<len(items):raise DomainError("INVALID_ARGUMENT","训练位置越界。")
    current=state(db,study,frozen,True);old=current.version
    changed=db.execute(update(EnglishStudyState).where(EnglishStudyState.study_session_id==study_id,EnglishStudyState.version==old).values(position=position,version=old+1).execution_options(synchronize_session=False))
    if changed.rowcount!=1:raise DomainError("VERSION_CONFLICT","另一个窗口已移动学习位置。")
    return {"position":position,"state_version":old+1}



def retest_get(db, task_id):
    from .retest import get
    return get(db, task_id)


def retest_save(db, task_id, answer_text, expected_version):
    from .retest import save
    return save(db, task_id, answer_text, expected_version)


def retest_check(db, task_id, answer_text, expected_version=None):
    from .retest import check
    return check(db, task_id, answer_text, expected_version)

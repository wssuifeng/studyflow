"""Bounded, explicitly scoped error reads. No full-workspace answer dump."""
import json
from datetime import datetime
from sqlalchemy import select,func
from studyflow.infrastructure.runtime import Service
from studyflow.modules.mistakes.query.models import MistakeNotebook
from studyflow.modules.mistakes.query.scope import notebook
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate,EnglishErrorEvidence,EnglishReviewItem
from studyflow.modules.mistakes.general.models import GeneralMistakeEntry,GeneralMistakeOccurrence
from studyflow.modules.learning.english.models import EnglishCheckAttempt
from studyflow.modules.learning.models import Submission
from studyflow.modules.reviews.models import ReviewFeedback
from studyflow.modules.learning.study_sessions import frozen_context
from studyflow.shared.domain import DomainError
from .cursor import fingerprint, encode, decode


class MistakesService(Service):
    def notebooks(self):
        from studyflow.modules.planning.models import PlanLine
        with self.session(read_only=True) as db:
            return {"notebooks":[{"id":b.id,"plan_line_id":b.plan_line_id,"domain":b.domain,"title":db.get(PlanLine,b.plan_line_id).name if b.plan_line_id else "未归属课程"} for b in db.scalars(select(MistakeNotebook).order_by(MistakeNotebook.scope_key,MistakeNotebook.domain))]}

    def _scope(self,db,plan_line_id=None,domain=None,notebook_id=None):
        if notebook_id:
            book=db.get(MistakeNotebook,notebook_id)
            if not book or domain and book.domain!=domain or plan_line_id and book.plan_line_id!=plan_line_id:raise DomainError("SCOPE_MISMATCH","分册不属于指定计划/领域。")
            return book,book.domain
        if not plan_line_id or domain not in {"general","english"}:raise DomainError("SCOPE_REQUIRED","必须指定分册，或计划与领域。")
        from studyflow.modules.planning.models import PlanLine
        if not db.get(PlanLine,plan_line_id):raise DomainError("OBJECT_NOT_FOUND","计划不存在。")
        return notebook(db,plan_line_id,domain),domain

    def _query(self,db,plan_line_id=None,domain=None,notebook_id=None,course_id=None,archived=False,objective_id=None,since=None,until=None,view="training_errors"):
        book,domain=self._scope(db,plan_line_id,domain,notebook_id)
        model=EnglishErrorAggregate if domain=="english" else GeneralMistakeEntry
        q=select(model).where(model.notebook_id==book.id if book else False,model.archived==archived)
        if course_id:q=q.where(model.course_id==course_id)
        if since or until:
            ev=EnglishErrorEvidence if domain=="english" else GeneralMistakeOccurrence
            key=ev.aggregate_id if domain=="english" else ev.entry_id
            eq=self._time(select(key),ev,since,until)
            q=q.where(model.id.in_(eq))
        if objective_id:
            if domain!="english":raise DomainError("INVALID_ARGUMENT","普通条目暂不支持英语目标标签。")
            q=q.where(model.objective_ids_json.contains('"'+objective_id+'"',autoescape=True))
        if view not in {"training_errors","review_queue"}:raise DomainError("INVALID_ARGUMENT","未知错误视图。")
        if domain=="english" and view=="review_queue":q=q.join(EnglishReviewItem,EnglishReviewItem.aggregate_id==model.id).where(EnglishReviewItem.status.in_(["PENDING","RETESTING"]))
        return q,domain,book

    def _time(self,query,model,since=None,until=None):
        try:
            if since:query=query.where(model.created_at>=datetime.fromisoformat(since))
            if until:query=query.where(model.created_at<=datetime.fromisoformat(until))
        except (ValueError,TypeError):raise DomainError("INVALID_ARGUMENT","时间范围必须为ISO时间戳。")
        return query

    def summary(self,**scope):
        with self.session(read_only=True) as db:
            q,domain,book=self._query(db,**scope)
            ids=q.with_only_columns((EnglishErrorAggregate if domain=="english" else GeneralMistakeEntry).id)
            total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
            result={"domain":domain,"notebook_id":book.id if book else None,"entry_total":total,"scope":scope}
            if domain=="english":
                result.update(failed_attempts=db.scalar(select(func.coalesce(func.sum(EnglishErrorAggregate.failed_attempts),0)).where(EnglishErrorAggregate.id.in_(ids))),failed_rounds=db.scalar(select(func.count(func.distinct(EnglishErrorEvidence.round_key))).where(EnglishErrorEvidence.aggregate_id.in_(ids))),review_total=db.scalar(select(func.count(EnglishReviewItem.id)).where(EnglishReviewItem.aggregate_id.in_(ids),EnglishReviewItem.status.in_(["PENDING","RETESTING"]))),valid_error_evidence=db.scalar(select(func.count(EnglishErrorEvidence.id)).where(EnglishErrorEvidence.aggregate_id.in_(ids),EnglishErrorEvidence.valid_error==True)))
            if domain=="english" and (scope.get("since") or scope.get("until")):
                eq=self._time(select(EnglishErrorEvidence).where(EnglishErrorEvidence.aggregate_id.in_(ids)),EnglishErrorEvidence,scope.get("since"),scope.get("until")).subquery()
                result["failed_attempts"]=db.scalar(select(func.count()).select_from(eq))
                result["failed_rounds"]=db.scalar(select(func.count(func.distinct(eq.c.round_key))))
                result["valid_error_evidence"]=db.scalar(select(func.count()).select_from(eq).where(eq.c.valid_error==True))
            result["counting_basis"]="失败尝试为历史未匹配/批改证据；轮次数按范围内学习轮次/任务去重；有效错误排除Agent已接受的表达。"
            return result

    def list(self,limit=30,cursor=None,**scope):
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100:raise DomainError("INVALID_ARGUMENT","limit为1—100。")
        with self.session(read_only=True) as db:
            q,domain,book=self._query(db,**scope)
            model=EnglishErrorAggregate if domain=="english" else GeneralMistakeEntry
            scope_hash=fingerprint(scope,domain,book.id if book else None)
            if cursor:q=q.where(model.id>decode(cursor,scope_hash))
            rows=list(db.scalars(q.order_by(model.id).limit(limit+1)))
            items=[]
            from studyflow.modules.courses.models import Course,Exercise
            for row in rows[:limit]:
                item={"id":row.id,"notebook_id":row.notebook_id,"course_id":row.course_id,"course_title":db.get(Course,row.course_id).title,"exercise_id":row.exercise_key,"rule_hash":row.rule_hash,"version":row.version,"archived":row.archived}
                ex=db.get(Exercise,row.exercise_key);item["title"]=ex.title if ex else "历史训练项"
                if domain=="english":
                    review=db.scalar(select(EnglishReviewItem).where(EnglishReviewItem.aggregate_id==row.id))
                    item.update(failed_attempts=row.failed_attempts,failed_rounds=row.failed_rounds,lifetime_failed_attempts=row.failed_attempts,lifetime_failed_rounds=row.failed_rounds,objective_ids=json.loads(row.objective_ids_json),review_status=review.status if review else None)
                    if scope.get("since") or scope.get("until"):
                        eq=self._time(select(EnglishErrorEvidence).where(EnglishErrorEvidence.aggregate_id==row.id),EnglishErrorEvidence,scope.get("since"),scope.get("until")).subquery()
                        item["failed_attempts"]=db.scalar(select(func.count()).select_from(eq))
                        item["failed_rounds"]=db.scalar(select(func.count(func.distinct(eq.c.round_key))))
                else:item["status"]=row.status
                items.append(item)
            return {"items":items,"domain":domain,"next_cursor":encode(rows[limit-1].id,scope_hash) if len(rows)>limit else None}

    def context(self,identifier,expected_version=None,limit=20,cursor=None,**scope):
        if not 1<=limit<=100:raise DomainError("INVALID_ARGUMENT","证据页最多100条。")
        with self.session(read_only=True) as db:
            q,domain,book=self._query(db,**scope)
            model=EnglishErrorAggregate if domain=="english" else GeneralMistakeEntry
            entry=db.scalar(q.where(model.id==identifier))
            if not entry:raise DomainError("SCOPE_MISMATCH","条目不属于指定范围。")
            if expected_version is not None and entry.version!=expected_version:raise DomainError("VERSION_CONFLICT","摘要已变化，请重新读取。")
            evidence_model=EnglishErrorEvidence if domain=="english" else GeneralMistakeOccurrence
            eq=select(evidence_model).where((evidence_model.aggregate_id if domain=="english" else evidence_model.entry_id)==entry.id)
            eq=self._time(eq,evidence_model,scope.get("since"),scope.get("until"))
            scope_hash=fingerprint(scope,domain,book.id if book else None,identifier)
            if cursor:eq=eq.where(evidence_model.id>decode(cursor,scope_hash))
            rows=list(db.scalars(eq.order_by(evidence_model.id).limit(limit+1)));evidence=[]
            for source in rows[:limit]:
                attempt=db.get(EnglishCheckAttempt,source.attempt_id) if domain=="english" and source.attempt_id else None
                feedback=db.get(ReviewFeedback,source.feedback_id) if source.feedback_id else None
                submission=db.get(Submission,attempt.submission_id if attempt else feedback.submission_id)
                frozen=frozen_context(submission)
                evidence.append({"id":source.id,"study_session_id":submission.study_session_id,"submission_id":submission.id,"attempt_id":attempt.id if attempt else None,"answer_text":attempt.answer_text if attempt else submission.answer_text,"result":json.loads(attempt.result_json) if attempt else None,"valid_error":source.valid_error if domain=="english" else True,"feedback":{"id":feedback.id,"summary":feedback.summary,"issues":json.loads(feedback.issues_json),"decision":feedback.decision} if feedback else None,"frozen_context":frozen})
            return {"id":entry.id,"version":entry.version,"rule_hash":entry.rule_hash,"evidence":evidence,"next_cursor":encode(rows[limit-1].id,scope_hash) if len(rows)>limit else None}

    def select_review(self,identifier,expected_version,idempotency_key,**scope):
        from studyflow.modules.learning.models import CourseWriteReceipt
        from studyflow.modules.learning.write_contract import digest
        from studyflow.shared.ids import new_id
        payload={"identifier":identifier,"expected_version":expected_version,"scope":scope}
        with self.session() as db:
            receipt=db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==idempotency_key))
            if receipt:
                if receipt.operation!="EN_REVIEW_SELECT" or receipt.payload_hash!=digest(payload):raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键用于另一复习请求。")
                return json.loads(receipt.result_json)
            q,domain,_=self._query(db,**scope)
            if domain!="english":raise DomainError("INVALID_ARGUMENT","此操作只收录英语复习项。")
            entry=db.scalar(q.where(EnglishErrorAggregate.id==identifier))
            if not entry or entry.version!=expected_version:raise DomainError("VERSION_CONFLICT","条目范围或版本变化。")
            from studyflow.modules.mistakes.english.projection import select_review
            item=select_review(db,entry,"MANUAL");db.flush()
            result={"review_id":item.id,"version":entry.version,"status":item.status}
            db.add(CourseWriteReceipt(id=new_id(),course_id=entry.course_id,operation="EN_REVIEW_SELECT",idempotency_key=idempotency_key,payload_hash=digest(payload),result_json=json.dumps(result)))
            self._event(db,"USER_ENGINE","english_review",item.id,"SELECT","收录指定英语复习项")
            return result

    def archive_preview(self,**scope):
        from studyflow.modules.mistakes.archive.service import snapshot
        with self.session(read_only=True) as db:return snapshot(self,db,scope)[1]

    def archive_apply(self,preview_hash,idempotency_key,**scope):
        from studyflow.modules.mistakes.archive.service import snapshot
        from studyflow.modules.learning.models import CourseWriteReceipt
        from studyflow.modules.learning.write_contract import digest
        from studyflow.shared.ids import new_id
        payload={"preview_hash":preview_hash,"scope":scope}
        with self.session() as db:
            receipt=db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==idempotency_key))
            if receipt:
                if receipt.operation!="MISTAKES_ARCHIVE" or receipt.payload_hash!=digest(payload):raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键用于另一归档请求。")
                return json.loads(receipt.result_json)
            rows,result=snapshot(self,db,scope)
            if not rows:raise DomainError("EMPTY_SCOPE","归档范围没有匹配记录，未执行写入。")
            if result["preview_hash"]!=preview_hash:raise DomainError("PREVIEW_CHANGED","归档预览已变化，未执行。")
            for row in rows:row.archived=True;row.version+=1
            self._event(db,"USER_ENGINE","mistakes",preview_hash,"ARCHIVE","逻辑归档，不删除证据。")
            response={"archived":len(rows),"logical_only":True}
            if rows:db.add(CourseWriteReceipt(id=new_id(),course_id=rows[0].course_id,operation="MISTAKES_ARCHIVE",idempotency_key=idempotency_key,payload_hash=digest(payload),result_json=json.dumps(response)))
            return response

    def retest_request(self,identifier,expected_version,idempotency_key,**scope):
        from studyflow.modules.mistakes.english.retest import publish
        with self.session() as db:
            from studyflow.modules.learning.models import CourseWriteReceipt
            from studyflow.modules.learning.write_contract import digest
            from studyflow.shared.ids import new_id
            payload={"identifier":identifier,"expected_version":expected_version,"scope":scope}
            receipt=db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==idempotency_key))
            if receipt:
                if receipt.operation!="EN_RETEST_PUBLISH" or receipt.payload_hash!=digest(payload):raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键用于不同复测发布请求。")
                return json.loads(receipt.result_json)
            q,domain,_=self._query(db,**scope)
            if domain!="english":raise DomainError("AGENT_RETEST_REQUIRED","普通复测需要Agent通过review.retest.publish明确编写任务。")
            aggregate=db.scalar(q.where(EnglishErrorAggregate.id==identifier))
            if not aggregate:raise DomainError("SCOPE_MISMATCH","错误不属于指定范围。")
            result=publish(db,aggregate,expected_version,idempotency_key)
            db.add(CourseWriteReceipt(id=new_id(),course_id=aggregate.course_id,operation="EN_RETEST_PUBLISH",idempotency_key=idempotency_key,payload_hash=digest(payload),result_json=json.dumps(result)))
            self._event(db,"USER_ENGINE","english_retest",result["task_id"],"PUBLISH","发布有冻结来源的英语无提示复测。")
            return result

"""One transaction for author-driven supplemental publication and evidence provenance."""
import json
from sqlalchemy import select, update
from studyflow.infrastructure.runtime import Service
from studyflow.infrastructure.markdown import safe_resolve
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.learning.write_contract import digest
from studyflow.modules.learning.models import CourseWriteReceipt
from studyflow.modules.planning.models import PlanLine
from studyflow.modules.courses.content import PROGRESSION_SCHEMA, STRUCTURED_SCHEMA, ENGLISH_TRAINING_SCHEMA
from studyflow.modules.courses.packages import inspect_package, package_lock, _import_package
from studyflow.modules.courses.english.progression import validate_chains
from studyflow.modules.mistakes.query.models import MistakeNotebook
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate, EnglishErrorEvidence
from studyflow.modules.mistakes.remediation.models import EnglishRemediationCourse, EnglishRemediationSource
from studyflow.modules.mistakes.remediation.query import get_course, list_courses

class EnglishRemediationApplication(Service):
    def _prepare(self,db,plan_line_id,path,objective_ids,rationale,sources):
        from studyflow.modules.courses.content import ident, text, sequence, obj
        plan=db.get(PlanLine,plan_line_id)
        if not plan:raise DomainError("OBJECT_NOT_FOUND","计划不存在。")
        if plan.status!="ACTIVE":raise DomainError("PLAN_NOT_ACTIVE","请先恢复计划后发布补充学习。")
        sequence(objective_ids,"objective_ids",1,5)
        for identifier in objective_ids:ident(identifier,"objective_ids")
        if len(set(objective_ids))!=len(objective_ids):raise DomainError("INVALID_ARGUMENT","目标标签不能重复。")
        text(rationale,"rationale",4000);sequence(sources,"sources",1,30)
        data,summary=inspect_package(safe_resolve(self.settings.workspace_root,path))
        if data["schema"] not in {PROGRESSION_SCHEMA,STRUCTURED_SCHEMA,ENGLISH_TRAINING_SCHEMA} or data["course"].get("learning_mode")!="english":raise DomainError("INVALID_ARGUMENT","补充学习需要 /4、/5 或 /6 英语课程与显式递进标识。")
        if data["plan_line"]!=plan.name:raise DomainError("SCOPE_MISMATCH","课程包计划与请求不一致。")
        chains=validate_chains(data,required=True)
        declared={o for l in data["lessons"] for ex in l.get("exercises",[]) for o in ex["english"].get("objective_ids",[])}
        if not set(objective_ids)<=declared:raise DomainError("INVALID_ARGUMENT","课程没有覆盖声明的补充学习目标。")
        frozen=[];seen=set()
        for source in sources:
            obj(source,"sources.item",{"aggregate_id","expected_version","evidence_ids"},{"aggregate_id","expected_version","evidence_ids"})
            if source["aggregate_id"] in seen:raise DomainError("INVALID_ARGUMENT","重复错误来源。")
            seen.add(source["aggregate_id"])
            aggregate=db.get(EnglishErrorAggregate,source["aggregate_id"])
            if not aggregate:raise DomainError("OBJECT_NOT_FOUND","英语错误不存在。")
            book=db.get(MistakeNotebook,aggregate.notebook_id)
            if book.domain!="english" or book.plan_line_id!=plan.id:raise DomainError("SCOPE_MISMATCH","错误证据不属于所选英语计划。")
            if aggregate.archived:raise DomainError("SOURCE_ARCHIVED","请选择活跃错误；归档事实仍保留。")
            if isinstance(source["expected_version"],bool) or aggregate.version!=source["expected_version"]:raise DomainError("VERSION_CONFLICT","英语错误已变化，请重新读取证据并预览。")
            sequence(source["evidence_ids"],"evidence_ids",1,10)
            if len(set(source["evidence_ids"]))!=len(source["evidence_ids"]):raise DomainError("INVALID_ARGUMENT","重复证据。")
            evidence=[]
            for identifier in source["evidence_ids"]:
                row=db.get(EnglishErrorEvidence,identifier)
                if not row or row.aggregate_id!=aggregate.id:raise DomainError("SCOPE_MISMATCH","证据不属于所选错误。")
                if not row.valid_error:raise DomainError("SOURCE_NOT_VALID_ERROR","已被接受的表达不能作为待补语法错误。")
                evidence.append(row.id)
            frozen.append({"aggregate_id":aggregate.id,"source_version":aggregate.version,"rule_hash":aggregate.rule_hash,"source_course_id":aggregate.course_id,"evidence_ids":sorted(evidence)})
        provenance={"plan_line_id":plan.id,"objective_ids":objective_ids,"rationale":rationale,"sources":frozen}
        preview_hash=digest({"content_hash":summary["content_hash"],"plan_version":plan.version,"provenance":provenance})
        return data,summary,provenance,preview_hash,chains

    def preview(self,**request):
        with self.session(read_only=True) as db:
            _,summary,provenance,preview_hash,chains=self._prepare(db,**request)
            return {"valid":True,**summary,"plan_line_id":request["plan_line_id"],"track":"SUPPLEMENT","source_count":len(provenance["sources"]),"evidence_count":sum(len(s["evidence_ids"]) for s in provenance["sources"]),"objective_ids":request["objective_ids"],"chains":chains,"preview_hash":preview_hash,"mainline_unchanged":True,"auto_resolves_original_errors":False}

    def publish(self,preview_hash,idempotency_key,**request):
        if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160:raise DomainError("INVALID_ARGUMENT","发布需要稳定幂等键。")
        payload_hash=digest({**request,"preview_hash":preview_hash})
        with package_lock(self.settings.workspace_root),self.session() as db:
            receipt=db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==idempotency_key))
            if receipt:
                if receipt.operation!="REMEDIATION_PUBLISH" or receipt.payload_hash!=payload_hash:raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已用于不同请求。")
                return json.loads(receipt.result_json)
            data,summary,provenance,current_hash,_=self._prepare(db,**request)
            if current_hash!=preview_hash:raise DomainError("PREVIEW_CHANGED","课程、计划或来源已变化，请重新预览。")
            provenance_hash=digest(provenance)
            imported=_import_package(self,data,summary,db=db,track="SUPPLEMENT")
            profile=db.get(EnglishRemediationCourse,imported["course_id"])
            if not imported["created"]:
                if not profile or profile.plan_line_id!=request["plan_line_id"] or profile.provenance_hash!=provenance_hash:raise DomainError("COURSE_REMEDIATION_CONFLICT","包身份已属于其他课程或错误来源；未改变其分组和来源。")
            else:
                profile=EnglishRemediationCourse(course_id=imported["course_id"],plan_line_id=request["plan_line_id"],objective_ids_json=json.dumps(request["objective_ids"]),rationale=request["rationale"],provenance_hash=provenance_hash)
                db.add(profile);db.flush()
                for source in provenance["sources"]:
                    # Recheck version at the write boundary even when a database lacks a global writer lease.
                    guarded=db.execute(update(EnglishErrorAggregate).where(EnglishErrorAggregate.id==source["aggregate_id"],EnglishErrorAggregate.version==source["source_version"]).values(version=EnglishErrorAggregate.version,updated_at=EnglishErrorAggregate.updated_at).execution_options(synchronize_session=False))
                    if guarded.rowcount!=1:raise DomainError("VERSION_CONFLICT","来源版本竞争，课程登记已回滚。")
                    for evidence_id in source["evidence_ids"]:db.add(EnglishRemediationSource(id=new_id(),course_id=profile.course_id,aggregate_id=source["aggregate_id"],evidence_id=evidence_id,source_version=source["source_version"],rule_hash=source["rule_hash"]))
                db.flush()
            result={"course_id":profile.course_id,"plan_line_id":profile.plan_line_id,"track":"SUPPLEMENT","created":imported["created"],"content_hash":summary["content_hash"],"source_count":len(provenance["sources"]),"mainline_unchanged":True,"auto_resolves_original_errors":False}
            db.add(CourseWriteReceipt(id=new_id(),course_id=profile.course_id,idempotency_key=idempotency_key,operation="REMEDIATION_PUBLISH",payload_hash=payload_hash,result_json=json.dumps(result,ensure_ascii=False)))
            self._event(db,"AGENT_CLI","course",profile.course_id,"REMEDIATION_PUBLISH","关联英语错误并发布补充课程；未改变原错误或主线。")
            return result

    def list(self,**scope):
        limit=scope.get("limit",30);offset=scope.get("offset",0)
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100 or isinstance(offset,bool) or not isinstance(offset,int) or not 0<=offset<=100000:raise DomainError("INVALID_ARGUMENT","读取需有界分页。")
        with self.session(read_only=True) as db:return list_courses(db,**scope)

    def get(self,course_id):
        with self.session(read_only=True) as db:return get_course(db,course_id)

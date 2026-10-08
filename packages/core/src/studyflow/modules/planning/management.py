"""Versioned personal plan edits; scheduling never changes learning evidence."""
import json
from datetime import date,time
from sqlalchemy import select,update
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.learning.write_contract import digest
from .models import PlanLine,PlanCourseItem,CourseScheduleItem,PlanWriteReceipt


def edit_plan(service,plan_line_id,expected_version,idempotency_key,operation,values):
    if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160 or not isinstance(values,dict) or isinstance(expected_version,bool) or not isinstance(expected_version,int):raise DomainError("INVALID_ARGUMENT","需要版本、稳定幂等键与values对象。")
    payload={"plan_line_id":plan_line_id,"expected_version":expected_version,"operation":operation,"values":values}
    with service.session() as db:
        receipt=db.scalar(select(PlanWriteReceipt).where(PlanWriteReceipt.idempotency_key==idempotency_key))
        if receipt:
            if receipt.payload_hash!=digest(payload):raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已用于不同计划修改。")
            return json.loads(receipt.result_json)
        plan=db.get(PlanLine,plan_line_id)
        if not plan:raise DomainError("OBJECT_NOT_FOUND","计划不存在。")
        if plan.version!=expected_version:raise DomainError("VERSION_CONFLICT","计划已被另一窗口更新。")
        items=list(db.scalars(select(PlanCourseItem).where(PlanCourseItem.plan_line_id==plan.id).order_by(PlanCourseItem.sequence_number)))
        by_course={i.course_id:i for i in items}
        if operation=="UPDATE":
            if set(values)-{"name","priority","status","focus_course_id"}:raise DomainError("INVALID_ARGUMENT","未知计划字段。")
            if "name" in values and (not isinstance(values["name"],str) or not 1<=len(values["name"].strip())<=120):raise DomainError("INVALID_ARGUMENT","名称1—120字符。")
            if "priority" in values and (isinstance(values["priority"],bool) or not isinstance(values["priority"],int) or not 1<=values["priority"]<=100):raise DomainError("INVALID_ARGUMENT","优先级范围1—100。")
            if values.get("status",plan.status) not in {"ACTIVE","PAUSED","ARCHIVED"}:raise DomainError("INVALID_ARGUMENT","status支持ACTIVE/PAUSED/ARCHIVED。")
            if values.get("focus_course_id") is not None and values["focus_course_id"] not in by_course:raise DomainError("INVALID_ARGUMENT","重点课程不属于计划。")
            for k,v in values.items():setattr(plan,k,v.strip() if k=="name" else v)
        elif operation=="REORDER":
            ordered=values.get("course_ids")
            if set(values)!={"course_ids"} or not isinstance(ordered,list) or len(ordered)!=len(items) or len(set(ordered))!=len(ordered) or set(ordered)!=set(by_course):raise DomainError("INVALID_ARGUMENT","重排必须包含计划内全部课程且不重复。")
            for n,cid in enumerate(ordered,1):by_course[cid].sequence_number=n
        elif operation=="SCHEDULE":
            if set(values)-{"course_id","date","start_time","end_time"}:raise DomainError("INVALID_ARGUMENT","未知日程字段。")
            item=by_course.get(values.get("course_id"))
            if not item:raise DomainError("INVALID_ARGUMENT","课程不属于计划。")
            try:
                day=date.fromisoformat(values["date"])
                start=time.fromisoformat(values["start_time"]) if values.get("start_time") else None
                end=time.fromisoformat(values["end_time"]) if values.get("end_time") else None
            except (ValueError,KeyError,TypeError) as exc:raise DomainError("INVALID_ARGUMENT","日期YYYY-MM-DD，时间HH:MM。") from exc
            if start and end and end<=start:raise DomainError("INVALID_ARGUMENT","结束时间必须晚于开始时间。")
            row=db.scalar(select(CourseScheduleItem).where(CourseScheduleItem.plan_course_item_id==item.id,CourseScheduleItem.scheduled_date==day))
            if not row:row=CourseScheduleItem(id=new_id(),plan_course_item_id=item.id,scheduled_date=day,position=item.sequence_number);db.add(row)
            row.start_time=start;row.end_time=end;row.status="PLANNED"
        elif operation in {"RESCHEDULE","CANCEL_SCHEDULE"}:
            row=db.get(CourseScheduleItem,values.get("schedule_id"))
            if not row or row.plan_course_item_id not in {i.id for i in items}:raise DomainError("INVALID_ARGUMENT","日程不属于计划。")
            if operation=="CANCEL_SCHEDULE":row.status="CANCELLED"
            else:
                try:day=date.fromisoformat(values["date"])
                except (KeyError,TypeError,ValueError) as exc:raise DomainError("INVALID_ARGUMENT","日期YYYY-MM-DD。") from exc
                if db.scalar(select(CourseScheduleItem.id).where(CourseScheduleItem.plan_course_item_id==row.plan_course_item_id,CourseScheduleItem.scheduled_date==day,CourseScheduleItem.id!=row.id)):raise DomainError("VERSION_CONFLICT","目标日期已有安排。")
                row.scheduled_date=day;row.status="PLANNED"
        else:raise DomainError("INVALID_ARGUMENT","不支持该计划操作。")
        # Explicit CAS guards two concurrent writers despite their earlier reads.
        changed=db.execute(update(PlanLine).where(PlanLine.id==plan.id,PlanLine.version==expected_version).values(version=expected_version+1).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise DomainError("VERSION_CONFLICT","计划版本竞争，全部修改已回滚。")
        result={"ok":True,"plan_line_id":plan.id,"version":expected_version+1,"operation":operation}
        db.add(PlanWriteReceipt(id=new_id(),idempotency_key=idempotency_key,payload_hash=digest(payload),result_json=json.dumps(result)))
        service._event(db,"USER_ENGINE","plan",plan.id,operation,"调整个人计划，不改变学习证据")
        db.flush();return result


def list_schedule(service,plan_line_id):
    with service.session() as db:
        if not db.get(PlanLine,plan_line_id):raise DomainError("OBJECT_NOT_FOUND","计划不存在。")
        rows=db.scalars(select(CourseScheduleItem).join(PlanCourseItem).where(PlanCourseItem.plan_line_id==plan_line_id).order_by(CourseScheduleItem.scheduled_date)).all()
        return {"items":[{"id":r.id,"course_id":r.plan_course_item.course_id,"date":r.scheduled_date.isoformat(),"status":r.status,"start_time":r.start_time.isoformat() if r.start_time else None,"end_time":r.end_time.isoformat() if r.end_time else None} for r in rows]}

"""Continuous plan notebooks with scoped blocks and frozen excerpt provenance."""
from __future__ import annotations
import hashlib
import json
import re
from html.parser import HTMLParser
from sqlalchemy import select, update
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.planning.models import PlanLine, PlanCourseItem
from studyflow.modules.courses.models import Course, Lesson
from .models import PlanNotebook, PlanNotebookReceipt, StudyNote, CourseStudySession
from .study_sessions import require_study


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data): self.parts.append(data)
    def handle_endtag(self, tag):
        if tag in {"p","div","li","h1","h2","h3","tr","td","th","pre","br"}: self.parts.append(" ")
    def handle_starttag(self, tag, attrs):
        if tag == "br": self.parts.append(" ")


def _normalize(text): return re.sub(r"\s+", " ", text).strip()


def _plan(db, pid):
    plan = db.get(PlanLine, pid) if isinstance(pid,str) else None
    if not plan: raise DomainError("OBJECT_NOT_FOUND", "学习计划不存在。")
    return plan


def _wire(row, pid):
    return {"plan_line_id":pid, "version":row.version if row else 0,
            "blocks":json.loads(row.blocks_json) if row else [],
            "updated_at":row.updated_at.isoformat() if row and row.updated_at else None}


def read_notebook(service, pid):
    with service.session() as db:
        _plan(db,pid)
        row=db.scalar(select(PlanNotebook).where(PlanNotebook.plan_line_id == pid))
        legacy=db.execute(select(StudyNote,CourseStudySession,Course).join(CourseStudySession,StudyNote.study_session_id == CourseStudySession.id)
                          .join(Course,CourseStudySession.course_id == Course.id).where(Course.plan_line_id == pid).order_by(StudyNote.created_at)).all()
        return {**_wire(row,pid), "legacy_notes":[{"id":note.id,"text":note.text,"study_session_id":study.id,
                "course_id":course.id,"course_title":course.title,"lesson_id":note.lesson_id}
                for note,study,course in legacy if note.text]}


def _blocks(db,pid,blocks):
    if not isinstance(blocks,list) or len(blocks)>1000: raise DomainError("INVALID_ARGUMENT","笔记需要不超过1000段的列表。")
    normalized=[]; ids=set(); size=0
    for item in blocks:
        if not isinstance(item,dict): raise DomainError("INVALID_ARGUMENT","每段笔记必须是对象。")
        bid=item.get("id"); text=item.get("text",""); quote=item.get("quote","")
        if not isinstance(bid,str) or not bid.strip() or len(bid)>64 or bid in ids: raise DomainError("INVALID_ARGUMENT","笔记段落ID需要唯一且不超过64字符。")
        if not isinstance(text,str) or len(text)>200000 or not isinstance(quote,str) or len(quote)>20000: raise DomainError("INVALID_ARGUMENT","笔记或摘录长度无效。")
        ids.add(bid); size+=len(text)+len(quote)
        cid=item.get("course_id") or None; lid=item.get("lesson_id") or None; sid=item.get("source_study_id") or None
        if any(value is not None and not isinstance(value,str) for value in (cid,lid,sid)): raise DomainError("INVALID_ARGUMENT","笔记关联ID必须是文本。")
        course=db.get(Course,cid) if cid else None
        if cid and (not course or course.plan_line_id!=pid and not db.scalar(select(PlanCourseItem.id).where(PlanCourseItem.plan_line_id==pid,PlanCourseItem.course_id==cid))):
            raise DomainError("INVALID_ARGUMENT","关联课程不属于这个学习计划。")
        lesson=db.get(Lesson,lid) if lid else None
        if lid and not (quote or sid) and (not course or not lesson or lesson.course_id!=cid): raise DomainError("INVALID_ARGUMENT","关联知识点不属于所选课程。")
        block={"id":bid,"text":text,"course_id":cid,"lesson_id":lid,"scope":"LESSON" if lid else "COURSE" if cid else "PLAN",
               "quote":quote,"source_study_id":sid,"course_title":course.title if course else None,
               "lesson_title":lesson.title if lesson else None,"content_hash":None}
        if quote or sid:
            if not quote or not sid or not cid or not lid: raise DomainError("INVALID_ARGUMENT","摘录需要原文、课程、知识点和冻结学习轮次。")
            study=require_study(db,sid,cid)
            snapshot=json.loads(study.snapshot_json); source=next((l for l in snapshot["lessons"] if l["id"]==lid),None)
            if source is None: raise DomainError("INVALID_ARGUMENT","摘录知识点不属于这个学习轮次。")
            plain=_Plain();plain.feed(source["rendered_html"])
            if not _normalize(quote) or _normalize(quote) not in _normalize("".join(plain.parts)):
                raise DomainError("INVALID_ARGUMENT","摘录不在本轮冻结正文中，未保存伪造来源。")
            anchor = item.get("source_block_id")
            if anchor is not None:
                if not isinstance(anchor,str) or not any(b["id"]==anchor for b in source.get("content_blocks",[])):
                    raise DomainError("INVALID_ARGUMENT","摘录内容块不属于本轮冻结知识点。")
                # Verify within the claimed block rather than accepting any lesson text.
                from studyflow.modules.courses.content import fallback_markdown
                chosen=next(b for b in source["content_blocks"] if b["id"]==anchor)
                if chosen["type"] != "practice":
                    from studyflow.infrastructure.markdown import render_markdown
                    local=_Plain(); local.feed(render_markdown(fallback_markdown({"title":"","blocks":[chosen]})))
                    if _normalize(quote) not in _normalize("".join(local.parts)):
                        raise DomainError("INVALID_ARGUMENT","摘录不在指定内容块中。")
                block["source_block_id"] = anchor
            block.update(course_title=snapshot["course"]["title"],lesson_title=source["title"],content_hash=study.content_hash)
        normalized.append(block)
    if size>1000000: raise DomainError("INVALID_ARGUMENT","计划笔记总长度不能超过100万字符。")
    return normalized


def save_notebook(service,pid,blocks,expected_version,key,source="USER_WEB"):
    if type(expected_version) is not int or expected_version<0: raise DomainError("INVALID_ARGUMENT","笔记需要非负整数版本号。")
    if not isinstance(key,str) or not key.strip() or len(key)>160: raise DomainError("INVALID_ARGUMENT","笔记需要稳定幂等键。")
    if not isinstance(blocks,list): raise DomainError("INVALID_ARGUMENT","blocks必须是列表。")
    digest=hashlib.sha256(json.dumps([pid,blocks,expected_version],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with service.session() as db:
        _plan(db,pid)
        receipt=db.scalar(select(PlanNotebookReceipt).where(PlanNotebookReceipt.idempotency_key==key))
        if receipt:
            if receipt.payload_hash!=digest: raise DomainError("IDEMPOTENCY_KEY_CONFLICT","笔记请求键已用于不同内容。")
            return json.loads(receipt.result_json)
        normalized=_blocks(db,pid,blocks)
        row=db.scalar(select(PlanNotebook).where(PlanNotebook.plan_line_id==pid))
        content=json.dumps(normalized,ensure_ascii=False)
        if row:
            changed=db.execute(update(PlanNotebook).where(PlanNotebook.id==row.id,PlanNotebook.version==expected_version)
                .values(blocks_json=content,version=expected_version+1).execution_options(synchronize_session=False))
            if changed.rowcount!=1: raise DomainError("VERSION_CONFLICT","笔记已在其他窗口或Agent中更新。","保留本机笔记，重新读取后手动合并；不要覆盖旧版本。")
            db.expire(row);db.refresh(row)
        else:
            if expected_version!=0: raise DomainError("VERSION_CONFLICT","笔记版本不存在。")
            row=PlanNotebook(id=new_id(),plan_line_id=pid,blocks_json=content,version=1);db.add(row);db.flush()
        result=_wire(row,pid)
        db.add(PlanNotebookReceipt(id=new_id(),idempotency_key=key,plan_line_id=pid,payload_hash=digest,result_json=json.dumps(result,ensure_ascii=False)))
        service._event(db,source,"plan_notebook",row.id,"SAVE","计划学习笔记更新")
        db.flush()
        return result

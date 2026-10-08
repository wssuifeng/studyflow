"""Read-only notebook discovery, source navigation and portable Markdown export."""
import json
from studyflow.shared.domain import DomainError
from .notebooks import read_notebook
from .study_sessions import require_study

def search(service,plan_line_id,query="",course_id=None,lesson_id=None):
    if not isinstance(query,str) or len(query)>200:raise DomainError("INVALID_ARGUMENT","搜索文本最多200字符。")
    data=read_notebook(service,plan_line_id)
    blocks=[b for b in data["blocks"] if (not course_id or b.get("course_id")==course_id) and (not lesson_id or b.get("lesson_id")==lesson_id) and (not query or query.casefold() in (b.get("text","")+" "+b.get("quote","")).casefold())]
    return {"plan_line_id":plan_line_id,"version":data["version"],"blocks":blocks,"count":len(blocks)}

def export(service,plan_line_id):
    data=read_notebook(service,plan_line_id)
    lines=["# 学习笔记","",f"计划：{plan_line_id}",""]
    for block in data["blocks"]:
        lines.extend(["## "+(block.get("lesson_title") or block.get("course_title") or "计划笔记"),""])
        if block.get("quote"):lines.extend(["> "+block["quote"].replace("\n","\n> "),""])
        lines.extend([block.get("text",""),""])
        if block.get("source_study_id"):lines.extend([f"来源学习轮次：{block['source_study_id']} · 知识点：{block.get('lesson_id')} · 内容版本：{block.get('content_hash')}",""])
    return {"filename":"StudyFlow-学习笔记.md","markdown":"\n".join(lines),"version":data["version"]}

def source(service,study_session_id,lesson_id,block_id=None):
    with service.session() as db:
        study=require_study(db,study_session_id)
        content=json.loads(study.snapshot_json)
        lesson=next((l for l in content["lessons"] if l["id"]==lesson_id),None)
        if not lesson:raise DomainError("OBJECT_NOT_FOUND","知识点不在该冻结版本中。","使用笔记保留的摘录。")
        block=next((b for b in lesson.get("content_blocks",[]) if b["id"]==block_id),None) if block_id else None
        if block_id and not block:raise DomainError("OBJECT_NOT_FOUND","引用组件不在该冻结版本中。","使用笔记保留的摘录。")
        return {"readonly":True,"study_session_id":study.id,"content_hash":study.content_hash,"course":content["course"],"lesson":lesson,"block":block}

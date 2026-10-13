"""Read-only, bounded projections carrying the aggregate version."""
from __future__ import annotations
import json
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.modules.planning.models import PlanLine
from studyflow.modules.learning.models import PlanNotebook
from . import sources
from .document import citations, invalid, plain


def find(db, pid):
    if not isinstance(pid, str) or not db.get(PlanLine, pid):
        raise DomainError("OBJECT_NOT_FOUND", "学习计划不存在。")
    return db.scalar(select(PlanNotebook).where(PlanNotebook.plan_line_id == pid))


def state(db, pid, row):
    if row and row.format_version not in {1, 2}:
        raise DomainError("NOTEBOOK_FORMAT_UNSUPPORTED", "笔记格式高于当前软件支持版本；禁止覆盖。", "使用兼容版本导出或读取，不要降级写入。")
    if row and row.format_version == 1:
        return sources.legacy(db, pid, json.loads(row.blocks_json))
    return (json.loads(row.document_json)["entries"] if row else []), sources.load(db, row)


def read(service, plan_line_id, course_id=None, lesson_id=None, entry_ids=None,
         query="", offset=0, limit=100, expected_version=None):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        invalid("笔记分页需要非负offset和1—100的limit。")
    if not isinstance(query, str) or len(query) > 200: invalid("笔记搜索文本超限。")
    if entry_ids is not None and (not isinstance(entry_ids, list) or not 1 <= len(entry_ids) <= 100 or not all(isinstance(x, str) for x in entry_ids)):
        invalid("记录ID读取需要1—100个ID。")
    if expected_version is not None and (type(expected_version) is not int or expected_version < 0): invalid("版本必须是非负整数。")
    with service.session(read_only=True) as db:
        row = find(db, plan_line_id); version = row.version if row else 0
        if expected_version is not None and version != expected_version:
            raise DomainError("VERSION_CONFLICT", "笔记分页期间版本已改变；请重新读取。")
        entries, source_map = state(db, plan_line_id, row)
        selected = [e for e in entries if (not course_id or e["course_id"] == course_id)
                    and (not lesson_id or e["lesson_id"] == lesson_id)
                    and (entry_ids is None or e["id"] in entry_ids)
                    and (not query or query.casefold() in plain(e["content"]).casefold())]
        page = selected[offset:offset + limit]
        related = set()
        def refs(nodes):
            for n in nodes:
                for m in n.get("marks", []):
                    if m["type"] == "citation": related.add(m["attrs"]["sourceId"])
                refs(n.get("content", []))
        for e in page: refs(e["content"])
        return {"plan_line_id": plan_line_id, "version": version, "format_version": row.format_version if row else 2,
                "entries": page, "sources": [source_map[s] for s in sorted(related)],
                "citations": citations(page, source_map), "offset": offset, "total": len(selected),
                "next_cursor": offset + limit if offset + limit < len(selected) else None,
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}

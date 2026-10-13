"""One notebook, one CAS and one receipt for an atomic ID-addressed batch."""
from __future__ import annotations
import copy
import hashlib
import json
from sqlalchemy import select, update
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.learning.models import PlanNotebook, PlanNotebookReceipt, PlanNotebookSource
from .queries import find, state
from . import sources
from .document import identity, invalid, validate_content, validate_document


def _place(entries, entry, operation):
    if "after_id" not in operation:
        same = [i for i, e in enumerate(entries) if (e["scope"], e["course_id"], e["lesson_id"]) == (entry["scope"], entry["course_id"], entry["lesson_id"])]
        at = same[-1] + 1 if same else len(entries)
    elif operation["after_id"] is None:
        same = [i for i, e in enumerate(entries) if (e["scope"], e["course_id"], e["lesson_id"]) == (entry["scope"], entry["course_id"], entry["lesson_id"])]
        at = same[0] if same else len(entries)
    else:
        anchor = next((i for i, e in enumerate(entries) if e["id"] == operation["after_id"]), None)
        if anchor is None: invalid("记录顺序锚点不存在。")
        if (entries[anchor]["scope"], entries[anchor]["course_id"], entries[anchor]["lesson_id"]) != (entry["scope"], entry["course_id"], entry["lesson_id"]):
            invalid("顺序锚点必须属于同一范围。")
        at = anchor + 1
    entries.insert(at, entry)


def apply(service, plan_line_id, expected_version, idempotency_key, operations, new_sources=None, source="USER_WEB"):
    if type(expected_version) is not int or expected_version < 0: invalid("需要非负整数笔记版本。")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160: invalid("需要稳定幂等键。")
    if not isinstance(operations, list) or len(operations) > 2000: invalid("笔记操作批次超限。")
    new_sources = new_sources if new_sources is not None else []
    if not isinstance(new_sources, list) or len(new_sources) > 100: invalid("一次最多注册100个出处。")
    payload = json.dumps([plan_line_id, expected_version, operations, new_sources], ensure_ascii=False, sort_keys=True)
    if len(payload.encode()) > 8_000_000: invalid("笔记命令超过8MB。")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with service.session() as db:
        row = find(db, plan_line_id)
        receipt = db.scalar(select(PlanNotebookReceipt).where(PlanNotebookReceipt.idempotency_key == idempotency_key))
        if receipt:
            if receipt.plan_line_id != plan_line_id or receipt.payload_hash != digest:
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "笔记请求键已用于不同内容。")
            return json.loads(receipt.result_json)
        version = row.version if row else 0
        if version != expected_version:
            raise DomainError("VERSION_CONFLICT", "笔记已在其他窗口或Agent中更新。", "保留本机内容，按记录ID比较后再合并。")
        entries, source_map = state(db, plan_line_id, row)
        entries = copy.deepcopy(entries); source_map = copy.deepcopy(source_map)
        original_sources = sources.load(db, row)
        for item in new_sources:
            if not isinstance(item, dict): invalid("出处必须是对象。")
            sid = identity(item.get("id"), "出处ID")
            if sid in source_map:
                stored = source_map[sid]
                if any(stored.get(k) != v for k, v in item.items()):
                    raise DomainError("NOTEBOOK_SOURCE_IMMUTABLE", "已保存出处不可修改。")
            else: source_map[sid] = sources.verify(db, plan_line_id, item)
        if len(source_map) > 10000: invalid("计划笔记出处超过10000条。")
        for op in operations:
            if not isinstance(op, dict): invalid("笔记操作必须是对象。")
            kind = op.get("type")
            allowed = {"insert_entry": {"type", "entry", "after_id"},
                       "replace_entry": {"type", "entry_id", "content"},
                       "remove_entry": {"type", "entry_id"},
                       "move_entry": {"type", "entry_id", "scope", "course_id", "lesson_id", "after_id"}}
            if kind not in allowed or set(op) - allowed[kind]: invalid("笔记命令含未知类型或字段。")
            if kind == "insert_entry":
                raw = op.get("entry")
                if not isinstance(raw, dict) or set(raw) - {"id", "scope", "course_id", "lesson_id", "content"}: invalid("新记录字段无效，标题由Core生成。")
                eid = identity(raw.get("id"), "记录ID")
                if any(e["id"] == eid for e in entries): invalid("记录ID已存在。")
                scope = raw.get("scope", "LESSON" if raw.get("lesson_id") else "COURSE" if raw.get("course_id") else "PLAN")
                entry = {"id": eid, **sources.membership(db, plan_line_id, raw.get("course_id"), raw.get("lesson_id"), scope),
                         "content": validate_content(raw.get("content"), source_map)}
                _place(entries, entry, op)
            else:
                eid = identity(op.get("entry_id"), "记录ID")
                index = next((i for i, e in enumerate(entries) if e["id"] == eid), None)
                if index is None: invalid("要修改的记录不存在。")
                if kind == "replace_entry": entries[index]["content"] = validate_content(op.get("content"), source_map)
                elif kind == "remove_entry": entries.pop(index)
                else:
                    entry = entries.pop(index)
                    entry.update(sources.membership(db, plan_line_id, op.get("course_id"), op.get("lesson_id"), op.get("scope")))
                    _place(entries, entry, op)
        validate_document(entries, source_map)
        document = json.dumps({"entries": entries}, ensure_ascii=False)
        if row:
            changed = db.execute(update(PlanNotebook).where(PlanNotebook.id == row.id, PlanNotebook.version == expected_version)
                                 .values(document_json=document, format_version=2, version=expected_version + 1).execution_options(synchronize_session=False))
            if changed.rowcount != 1: raise DomainError("VERSION_CONFLICT", "笔记已被其他写者更新。")
            db.expire(row); db.refresh(row)
        else:
            row = PlanNotebook(id=new_id(), plan_line_id=plan_line_id, blocks_json="[]", document_json=document, format_version=2, version=1)
            db.add(row); db.flush()
        for sid, data in source_map.items():
            if sid not in original_sources:
                db.add(PlanNotebookSource(notebook_id=row.id, id=sid, data_json=json.dumps(data, ensure_ascii=False)))
        result = {"plan_line_id": plan_line_id, "format_version": 2, "version": row.version,
                  "changed_entry_ids": list(dict.fromkeys(op.get("entry_id") or op.get("entry", {}).get("id") for op in operations)),
                  "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                  "sources": [source_map[item["id"]] for item in new_sources]}
        db.add(PlanNotebookReceipt(id=new_id(), plan_line_id=plan_line_id, idempotency_key=idempotency_key,
                                  payload_hash=digest, result_json=json.dumps(result, ensure_ascii=False)))
        service._event(db, source, "plan_notebook", row.id, "APPLY", "计划笔记增量更新")
        db.flush()
        return result

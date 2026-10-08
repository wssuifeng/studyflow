"""Private scratch notes, never formal answers or review work."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, update

from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from .models import StudyNote, StudyNoteReceipt
from .study_sessions import require_study


def _summary(row: StudyNote) -> dict:
    # First response and JSON receipt replay must have identical wire types.
    return {"id": row.id, "lesson_id": row.lesson_id, "text": row.text,
            "version": row.version, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def read_notes(service, study_id: str) -> dict:
    with service.session() as db:
        require_study(db, study_id)
        rows = db.scalars(select(StudyNote).where(StudyNote.study_session_id == study_id)).all()
        return {"study_session_id": study_id, "notes": [_summary(row) for row in rows]}


def save_note(service, study_id: str, lesson_id: str, text: str, expected_version: int, key: str, source: str = "USER_WEB") -> dict:
    if not isinstance(text, str) or len(text) > 200_000:
        raise DomainError("INVALID_ARGUMENT", "草稿必须为不超过20万字符的文本。")
    if type(expected_version) is not int or expected_version < 0:
        raise DomainError("INVALID_ARGUMENT", "草稿需要非负整数版本号，首次为0。")
    if not isinstance(key, str) or not key.strip() or len(key) > 160:
        raise DomainError("INVALID_ARGUMENT", "草稿需要1—160字符的稳定幂等键。")
    digest = hashlib.sha256(json.dumps([study_id, lesson_id, text, expected_version], ensure_ascii=False).encode()).hexdigest()
    with service.session() as db:
        receipt = db.scalar(select(StudyNoteReceipt).where(StudyNoteReceipt.idempotency_key == key))
        if receipt:
            if receipt.payload_hash != digest:
                raise DomainError("IDEMPOTENCY_KEY_CONFLICT", "草稿请求键已用于不同内容。", "原请求重试使用原内容与原键。")
            return json.loads(receipt.result_json)
        study = require_study(db, study_id)
        if lesson_id not in {row["id"] for row in json.loads(study.snapshot_json)["lessons"]}:
            raise DomainError("INVALID_ARGUMENT", "草稿知识点不属于本轮课程。")
        row = db.scalar(select(StudyNote).where(StudyNote.study_session_id == study_id, StudyNote.lesson_id == lesson_id))
        if row:
            changed = db.execute(update(StudyNote).where(StudyNote.id == row.id, StudyNote.version == expected_version)
                                 .values(text=text, version=expected_version + 1).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise DomainError("VERSION_CONFLICT", "草稿已在其他窗口更新。", "本机文字已保留；重新读取后确认要保留的版本。")
            db.expire(row)
            db.refresh(row)
        else:
            if expected_version != 0:
                raise DomainError("VERSION_CONFLICT", "草稿版本不存在，不能覆盖。")
            row = StudyNote(id=new_id(), study_session_id=study_id, lesson_id=lesson_id, text=text, version=1)
            db.add(row)
            db.flush()
        result = {"study_session_id": study_id, "note": _summary(row)}
        db.add(StudyNoteReceipt(id=new_id(), idempotency_key=key, study_session_id=study_id,
                               payload_hash=digest, result_json=json.dumps(result, ensure_ascii=False)))
        service._event(db, source, "study_note", row.id, "SAVE", "知识点私人草稿更新")
        db.flush()
        return result

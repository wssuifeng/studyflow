"""Authorized removal of obsolete per-round scratch content, not plan notes."""
from __future__ import annotations

import hashlib
import json
from sqlalchemy import delete, select
from studyflow.shared.domain import DomainError
from .models import StudyNote, StudyNoteReceipt


def _inventory(db, workspace_root):
    # Include receipts: their replay payloads contain the old text as well.
    notes = db.execute(select(StudyNote.id, StudyNote.study_session_id,
                              StudyNote.lesson_id, StudyNote.version, StudyNote.text)
                       .order_by(StudyNote.id)).all()
    receipts = db.execute(select(StudyNoteReceipt.id, StudyNoteReceipt.idempotency_key,
                                 StudyNoteReceipt.payload_hash, StudyNoteReceipt.result_json)
                          .order_by(StudyNoteReceipt.id)).all()
    digest = hashlib.sha256(json.dumps(
        [str(workspace_root), [list(row) for row in notes], [list(row) for row in receipts]],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {"scope": "legacy-study-notes", "workspace_root": str(workspace_root),
            "note_count": len(notes), "nonempty_note_count": sum(bool(row.text) for row in notes),
            "receipt_count": len(receipts), "preview_token": digest,
            "preserved": ["plan_notebooks", "plan_notebook_sources", "courses",
                          "course_study_sessions", "answers", "submissions", "reviews", "retests"]}


def cleanup(service, *, confirm=False, preview_token=None):
    if type(confirm) is not bool:
        raise DomainError("INVALID_ARGUMENT", "confirm 必须为布尔值。")
    if confirm and (not isinstance(preview_token, str) or len(preview_token) != 64):
        raise DomainError("PREVIEW_REQUIRED", "删除前需确认 dry-run 的 preview_token。")
    if confirm and service.runtime.read_only:
        raise DomainError("READ_ONLY_OPERATION", "只读连接不能执行草稿清理。")
    with service.session(read_only=True if not confirm else None) as db:
        before = _inventory(db, service.settings.workspace_root)
        if not confirm:
            return before
        if preview_token != before["preview_token"]:
            raise DomainError("PREVIEW_CHANGED", "旧草稿清单已变化，未执行删除。",
                              "重新运行 dry-run，确认新范围后再删除。")
        deleted_receipts = db.execute(delete(StudyNoteReceipt)).rowcount
        deleted_notes = db.execute(delete(StudyNote)).rowcount
        if deleted_notes or deleted_receipts:
            service._event(db, "AGENT_CLI", "legacy_study_notes", "workspace", "PURGE",
                           f"用户授权删除旧草稿{deleted_notes}条、保存回执{deleted_receipts}条；保留计划笔记及学习作答")
        after = _inventory(db, service.settings.workspace_root)
        return {**after, "deleted_notes": deleted_notes, "deleted_receipts": deleted_receipts}

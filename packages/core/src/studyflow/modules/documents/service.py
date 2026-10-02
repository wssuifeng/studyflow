from __future__ import annotations
from pathlib import Path
from sqlalchemy import select
from studyflow.shared.domain import DomainError
from studyflow.infrastructure.markdown import inspect_document, safe_resolve
from studyflow.modules.documents.models import Document
from studyflow.shared.ids import new_id


from studyflow.infrastructure.runtime import Runtime, Service


class DocumentsService(Service):
    def check_document(self, relative_path: str) -> Document:
        with self.session() as db:
            inspection = inspect_document(self.settings.workspace_root, relative_path)
            document = db.scalar(select(Document).where(Document.relative_path == relative_path))
            if not document:
                document = Document(id=new_id(), relative_path=relative_path)
                db.add(document)
            document.status = inspection.status
            document.file_size = inspection.file_size
            document.modified_at = inspection.modified_at
            document.content_hash = inspection.content_hash
            return document

    def list_documents(self) -> list[Document]:
        with self.session() as db:
            return db.scalars(select(Document).order_by(Document.status, Document.relative_path)).all()

    def read_document(self, relative_path: str, render: bool = True) -> dict:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise DomainError("INVALID_ARGUMENT", "document.read 需要相对路径。", "传入工作区内 Markdown 文件的相对路径。")
        raw_path = Path(relative_path)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise DomainError("PATH_OUTSIDE_WORKSPACE", "文档路径必须是工作区内不含上级跳转的相对路径。", "改用工作区内 Markdown 文件的相对路径。")
        if raw_path.suffix.lower() not in {".md", ".markdown"}:
            raise DomainError("UNSUPPORTED_DOCUMENT_TYPE", "文档读取目前只接受 Markdown 文件。", "使用 .md 或 .markdown 文件。")
        normalized = raw_path.as_posix()
        candidate = safe_resolve(self.settings.workspace_root, normalized)
        inspection = inspect_document(self.settings.workspace_root, normalized, render=render)
        if inspection.status == "MISSING":
            raise DomainError("DOCUMENT_NOT_FOUND", f"Markdown 文件不存在：{normalized}", "确认相对路径后重试。")
        if inspection.status != "PRESENT":
            raise DomainError("DOCUMENT_UNREADABLE", f"Markdown 文件无法读取：{normalized}", "确认文件使用 UTF-8 编码且当前用户有读取权限。")
        try:
            markdown_text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DomainError("DOCUMENT_UNREADABLE", f"Markdown 文件无法读取：{normalized}", "确认文件使用 UTF-8 编码且当前用户有读取权限。") from exc
        return {
            "path": inspection.relative_path,
            "status": inspection.status,
            "markdown": markdown_text,
            "html": inspection.html,
            "file_size": inspection.file_size,
            "modified_at": inspection.modified_at,
            "content_hash": inspection.content_hash,
        }

from __future__ import annotations
import typer
from .. import runtime
from ..runtime import output, fail
from ..registry import document_app


@document_app.command("read")
def document_read(path: str = typer.Option(..., "--path"), format: str = typer.Option("text", "--format")) -> None:
    try:
        output({"ok": True, **runtime.service().read_document(path)}, format)
    except Exception as exc:
        fail(exc)

@document_app.command("check")
def document_check(relative_path: str = typer.Option(..., "--path"), format: str = typer.Option("text", "--format")) -> None:
    try:
        doc = runtime.service().check_document(relative_path)
        output({"ok": True, "id": doc.id, "path": doc.relative_path, "status": doc.status, "size": doc.file_size}, format)
    except Exception as exc:
        fail(exc)

from __future__ import annotations
import json
from pathlib import Path
import typer
from .. import runtime
from ..runtime import output, fail
from ..registry import course_app, course_answers_app


@course_app.command("list")
def course_list(plan_line_id: str | None = typer.Option(None, "--plan-line"), format: str = typer.Option("text", "--format")) -> None:
    try:
        rows = runtime.service().list_courses(plan_line_id)
        output({"ok": True, "courses": [{"id": row.id, "title": row.title, "summary": row.summary, "subject": row.subject, "content_type": row.content_type, "difficulty": row.difficulty, "source_type": row.source_type, "plan_line": row.plan_line.name if row.plan_line else None} for row in rows]}, format)
    except Exception as exc:
        fail(exc)

@course_app.command("detail")
def course_detail(course_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    """读取课程、多知识点、阅读进度及作答状态。"""
    try:
        output({"ok": True, **runtime.service().course_detail(course_id)}, format)
    except Exception as exc:
        fail(exc)

@course_app.command("import")
def course_import(file_path: Path = typer.Option(..., "--file", exists=True, readable=True), format: str = typer.Option("text", "--format")) -> None:
    try:
        result = runtime.service().import_course_markdown(file_path)
        output({"ok": True, **result}, format)
    except Exception as exc:
        fail(exc)

@course_answers_app.command("get")
def course_answers_get(course_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    """读取本课原答案、草稿、批改和后续行动。"""
    try:
        output({"ok": True, **runtime.service().course_answer_sheet(course_id)}, format)
    except Exception as exc:
        fail(exc)

def _write_course_answers_file(course_id: str, file: Path, key: str, operation: str, format: str) -> None:
    try:
        payload = json.loads(file.read_text(encoding="utf-8-sig"))
        answers = payload.get("answers") if isinstance(payload, dict) else payload
        result = runtime.service().write_course_answers(course_id, answers, operation, key, source="AGENT_CLI", study_session_id=payload.get("study_session_id") if isinstance(payload, dict) else None)
        output({"ok": True, **result}, format)
    except Exception as exc:
        fail(exc)

@course_answers_app.command("save")
def course_answers_save(course_id: str = typer.Option(..., "--id"),
                        file: Path = typer.Option(..., "--file", exists=True, readable=True),
                        idempotency_key: str = typer.Option(..., "--idempotency-key"),
                        format: str = typer.Option("text", "--format")) -> None:
    """从 JSON 一次事务保存整课草稿；空白答案允许保留。"""
    _write_course_answers_file(course_id, file, idempotency_key, "DRAFT_SAVE", format)

@course_answers_app.command("submit")
def course_answers_submit(course_id: str = typer.Option(..., "--id"),
                          file: Path = typer.Option(..., "--file", exists=True, readable=True),
                          idempotency_key: str = typer.Option(..., "--idempotency-key"),
                          format: str = typer.Option("text", "--format")) -> None:
    """一次事务提交本课所有待作答题；不可覆盖已提交的原答案。"""
    _write_course_answers_file(course_id, file, idempotency_key, "SUBMIT", format)


@course_app.command("study-open")
def course_study_open(course_id: str = typer.Option(..., "--id"),
                      idempotency_key: str = typer.Option(..., "--idempotency-key"),
                      new_version: bool = typer.Option(False, "--new-version"),
                      format: str = typer.Option("text", "--format")) -> None:
    """开始或恢复固定版本学习；新版只在上一轮收口后显式开启。"""
    try:
        output({"ok": True, **runtime.service().open_course_study(course_id, idempotency_key, new_version)}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("study-detail")
def course_study_detail(study_session_id: str = typer.Option(..., "--study-id"),
                        format: str = typer.Option("text", "--format")) -> None:
    """只读冻结材料、阅读位置与本轮状态，不开启新学习。"""
    try:
        output({"ok": True, **runtime.service().course_study_detail(study_session_id)}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("notes-get")
def notes_get(study_id: str = typer.Option(...,"--study-id"), format: str = typer.Option("text","--format")):
    try: output({"ok":True,**runtime.service().study_notes(study_id)},format)
    except Exception as exc: fail(exc)

@course_app.command("notes-save")
def notes_save(study_id: str = typer.Option(...,"--study-id"), lesson_id: str = typer.Option(...,"--lesson-id"), file: str = typer.Option(...,"--file"), expected_version: int = typer.Option(...,"--expected-version"), idempotency_key: str = typer.Option(...,"--idempotency-key"), format: str = typer.Option("text","--format")):
    """保存知识点个人草稿，不生成正式答案或批改任务。"""
    try:
        from studyflow.infrastructure.markdown import safe_resolve
        from studyflow.shared.domain import DomainError

        service = runtime.service()
        path = safe_resolve(service.settings.workspace_root, file)
        if not path.is_file():
            raise DomainError("DOCUMENT_NOT_FOUND", "草稿文本文件不存在。", "指定工作区内的 UTF-8 文本文件。")
        if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
            raise DomainError("UNSUPPORTED_DOCUMENT_TYPE", "草稿接受 TXT 或 Markdown 文本文件。", "使用 .txt、.md 或 .markdown 文件。")
        if path.stat().st_size > 800_003:
            raise DomainError("INVALID_ARGUMENT", "草稿必须为不超过20万字符的文本。")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise DomainError("DOCUMENT_UNREADABLE", "草稿文件无法按 UTF-8 读取。", "检查编码和读取权限。") from exc
        output({"ok": True, **service.save_study_note(study_id, lesson_id, text,
            expected_version, idempotency_key, source="AGENT_CLI")}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("validate-package")
def course_validate_package(file_path: Path = typer.Option(..., "--file", exists=True, readable=True), format: str = typer.Option("text", "--format")) -> None:
    """只校验整课JSON包，不初始化工作区或写入数据库。"""
    try:
        from studyflow.modules.courses.packages import inspect_package
        output({"ok": True, **inspect_package(file_path)[1]}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("import-package")
def course_import_package(file_path: Path = typer.Option(..., "--file", exists=True, readable=True), format: str = typer.Option("text", "--format")) -> None:
    """验证完整课程后原子登记；相同包可重放，不覆盖旧课程。"""
    try:
        output({"ok": True, **runtime.service().import_course_package(file_path)}, format)
    except Exception as exc:
        fail(exc)

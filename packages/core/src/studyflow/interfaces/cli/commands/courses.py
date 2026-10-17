from __future__ import annotations
import hashlib
import json
from pathlib import Path
import typer
from .. import runtime
from ..runtime import output, fail
from ..registry import course_app, course_answers_app


@course_app.command("list")
def course_list(plan_line_id: str | None = typer.Option(None, "--plan-line"), format: str = typer.Option("text", "--format")) -> None:
    try:
        rows = runtime.service(read_only=True).list_courses(plan_line_id)
        output({"ok": True, "courses": [{"id": row.id, "title": row.title, "summary": row.summary, "subject": row.subject, "content_type": row.content_type, "difficulty": row.difficulty, "source_type": row.source_type, "plan_line": row.plan_line.name if row.plan_line else None} for row in rows]}, format)
    except Exception as exc:
        fail(exc, read_only=True)

@course_app.command("detail")
def course_detail(course_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    """读取课程、多知识点、阅读进度及作答状态。"""
    try:
        output({"ok": True, **runtime.service(read_only=True).course_detail(course_id)}, format)
    except Exception as exc:
        fail(exc, read_only=True)

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
        output({"ok": True, **runtime.service(read_only=True).course_answer_sheet(course_id)}, format)
    except Exception as exc:
        fail(exc, read_only=True)

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
    """开始或恢复学习；材料发布重置后自动读新版，存量阻断可经授权使用reset-learning。"""
    try:
        output({"ok": True, **runtime.service().open_course_study(course_id, idempotency_key, new_version)}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("study-detail")
def course_study_detail(study_session_id: str = typer.Option(..., "--study-id"),
                        format: str = typer.Option("text", "--format")) -> None:
    """只读冻结材料、阅读位置与本轮状态，不开启新学习。"""
    try:
        output({"ok": True, **runtime.service(read_only=True).course_study_detail(study_session_id)}, format)
    except Exception as exc:
        fail(exc, read_only=True)


@course_app.command("notes-get")
def notes_get(study_id: str = typer.Option(...,"--study-id"), format: str = typer.Option("text","--format")):
    try: output({"ok":True,**runtime.service(read_only=True).study_notes(study_id)},format)
    except Exception as exc: fail(exc, read_only=True)

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
        fail(exc, read_only=True)


@course_app.command("import-package")
def course_import_package(file_path: Path = typer.Option(..., "--file", exists=True, readable=True), format: str = typer.Option("text", "--format")) -> None:
    """验证完整课程后原子登记；相同包可重放，不覆盖旧课程。"""
    try:
        output({"ok": True, **runtime.service().import_course_package(file_path)}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("readback-check")
def course_readback_check(course_id: str = typer.Option(..., "--course"),
                          plan_line: str | None = typer.Option(None, "--plan-line"),
                          format: str = typer.Option("text", "--format")) -> None:
    """只读核对学习者当前活动轮读到的材料是否为最新；不开租约、不写任何文件。"""
    try:
        from studyflow.modules.learning.study_sessions import capture, current_study
        service = runtime.service(read_only=True)
        course = service.course_detail(course_id)["course"]
        with service.session(read_only=True) as db:
            study = current_study(db, course_id)
            active_round = None if study is None or study.abandoned_at is not None else {
                "study_session_id": study.id, "revision": study.revision,
                "content_hash": study.content_hash, "abandoned": False,
            }
        # capture 复用学习轮开启时的同一材料哈希算法；--plan-line 不属于本课时抛 SCOPE_MISMATCH。
        current_capture_hash = capture(service, course_id, plan_line)[1]
        if active_round is None:
            readback, next_action = "no_active_round", "课程当前没有活动学习轮；下次打开课程即从最新材料开始。"
        elif active_round["content_hash"] == current_capture_hash:
            readback, next_action = "current", "活动学习轮读到的就是最新材料，无需重开课程。"
        else:
            readback, next_action = "stale", "学习材料已更新而学习轮未重置；经用户授权运行course reset-learning的dry-run/confirm，再读取最新材料。"
        output({"ok": True, "course_id": course_id, "learning_mode": course.get("learning_mode"),
                "latest_revision": course.get("content_revision"), "active_round": active_round,
                "current_capture_hash": current_capture_hash, "readback": readback,
                "next_action": next_action}, format)
    except Exception as exc:
        fail(exc, read_only=True)


def _quality_read_bytes(path: Path, label: str) -> bytes:
    """Read one quality-check input file as raw bytes; unreadable → DOCUMENT_UNREADABLE (W1 §3)."""
    from studyflow.shared.domain import DomainError

    if not path.is_file():
        raise DomainError("DOCUMENT_UNREADABLE", f"{label}文件不存在：{path}", "提供存在的文件路径。")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DomainError("DOCUMENT_UNREADABLE", f"{label}文件无法读取：{path}", "检查读取权限与路径。") from exc


def _quality_decode_json(raw: bytes, label: str):
    """Decode UTF-8(-BOM) bytes and parse JSON; undecodable → DOCUMENT_UNREADABLE, illegal JSON → INVALID_ARGUMENT."""
    from studyflow.shared.domain import DomainError

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DomainError("DOCUMENT_UNREADABLE", f"{label}文件无法按 UTF-8 读取。", "检查文件编码。") from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DomainError("INVALID_ARGUMENT", f"{label}不是合法JSON。", "修正JSON语法后重试。") from exc


def _quality_load_json(path: Path, label: str):
    return _quality_decode_json(_quality_read_bytes(path, label), label)


def _quality_object(value, label: str) -> dict:
    from studyflow.shared.domain import DomainError

    if not isinstance(value, dict):
        raise DomainError("INVALID_ARGUMENT", f"{label}必须是JSON对象。", "按W1设计§3的输入结构提供。")
    return value


def _quality_long_section_chars(value: str) -> int:
    from studyflow.shared.domain import DomainError

    try:
        threshold = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_ARGUMENT", "--long-section-chars 必须是正整数。", f"当前值：{value!r}。") from exc
    if threshold <= 0:
        raise DomainError("INVALID_ARGUMENT", "--long-section-chars 必须是正整数。", f"当前值：{threshold}；不接受零或负数。")
    return threshold


@course_app.command("quality-check")
def course_quality_check(file_path: Path = typer.Option(..., "--file", help="整课包路径；字节hash即报告绑定的package_sha256"),
                         blueprint: Path | None = typer.Option(None, "--blueprint", help="目标/教学链蓝图JSON"),
                         sources: Path | None = typer.Option(None, "--sources", help="作者声明来源清单JSON，仅记录声明，不访问网络"),
                         related: list[Path] | None = typer.Option(None, "--related", help="同模板/同链追查的对照包JSON，可重复"),
                         validation_receipt: Path | None = typer.Option(None, "--validation-receipt", help="validate-package的结果回执JSON"),
                         rendering_receipt: Path | None = typer.Option(None, "--rendering-receipt", help="实际渲染检查的作者回执JSON"),
                         long_section_chars: str = typer.Option("400", "--long-section-chars", help="小节超长阈值，正整数"),
                         format: str = typer.Option("text", "--format")) -> None:
    """只读的确定性制课质量检查（W1设计§3）：五类分类advisories、教学链清单与发布关口；不初始化工作区或数据库。"""
    try:
        from studyflow.modules.courses.authoring_quality import analyze

        raw = _quality_read_bytes(file_path, "课程包")
        package = _quality_object(_quality_decode_json(raw, "课程包"), "课程包")
        report = analyze(
            package,
            hashlib.sha256(raw).hexdigest(),
            blueprint=_quality_object(_quality_load_json(blueprint, "--blueprint"), "--blueprint") if blueprint else None,
            sources=_quality_load_json(sources, "--sources") if sources else None,
            receipt=_quality_object(_quality_load_json(validation_receipt, "--validation-receipt"), "--validation-receipt") if validation_receipt else None,
            related=[_quality_object(_quality_load_json(path, "--related"), "--related") for path in related or []],
            long_section_chars=_quality_long_section_chars(long_section_chars),
            rendering_receipt=_quality_object(_quality_load_json(rendering_receipt, "--rendering-receipt"), "--rendering-receipt") if rendering_receipt else None,
        )
        output({"ok": True, **report}, format)
    except Exception as exc:
        fail(exc, read_only=True)

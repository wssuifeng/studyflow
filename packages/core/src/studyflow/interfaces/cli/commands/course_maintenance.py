"""Agent-authorized content replacement and current-learning reset."""
from pathlib import Path
import typer
from ..registry import course_app
from .. import runtime
from ..runtime import output, fail
from studyflow.shared.domain import DomainError


@course_app.command("reset-learning")
def reset_learning(course_id: str=typer.Option(...,"--id"),
    dry_run: bool=typer.Option(False,"--dry-run"), confirm: bool=typer.Option(False,"--confirm"),
    state_hash: str|None=typer.Option(None,"--state-hash"),
    content_hash: str|None=typer.Option(None,"--content-hash"),
    idempotency_key: str|None=typer.Option(None,"--idempotency-key"),
    format: str=typer.Option("text","--format")):
    """获授权重置本课并采用最新材料；允许有草稿/已提交，笔记与历史保留。先dry-run再confirm。"""
    try:
        if dry_run == confirm:
            raise DomainError("CONFIRMATION_REQUIRED", "必须且只能使用--dry-run或--confirm。")
        from studyflow.modules.learning.reset import preview, apply
        service=runtime.service(read_only=dry_run)
        result=preview(service.learning,course_id) if dry_run else apply(service.learning,
            course_id,state_hash,content_hash,idempotency_key,confirm=True)
        output(result,format)
    except Exception as exc:
        fail(exc,read_only=dry_run)


@course_app.command("update-preview")
def update_preview(course_id: str=typer.Option(...,"--id"),
    file: Path=typer.Option(...,"--file",exists=True,readable=True),
    expected_revision: int=typer.Option(...,"--expected-revision",min=1),
    format: str=typer.Option("text","--format")):
    """预览同一课程ID的内容覆盖，不因已有学习记录拒绝。"""
    try:
        from studyflow.modules.courses.revisions import preview
        output(preview(runtime.service(read_only=True).courses,course_id,file,expected_revision),format)
    except Exception as exc:fail(exc,read_only=True)


@course_app.command("update-apply")
def update_apply(course_id: str=typer.Option(...,"--id"),
    file: Path=typer.Option(...,"--file",exists=True,readable=True),
    expected_revision: int=typer.Option(...,"--expected-revision",min=1),
    preview_hash: str=typer.Option(...,"--preview-hash"),
    idempotency_key: str=typer.Option(...,"--idempotency-key"),
    format: str=typer.Option("text","--format")):
    """应用预览过的课程覆盖；内容实际变化时同时重置当前学习，保留笔记和历史。"""
    try:
        from studyflow.modules.courses.revisions import apply
        output(apply(runtime.service().courses,course_id,file,expected_revision,preview_hash,idempotency_key),format)
    except Exception as exc:fail(exc)

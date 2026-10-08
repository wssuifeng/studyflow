from __future__ import annotations
from pathlib import Path
import typer
from studyflow.config import Settings
from studyflow.workspace import export_workspace, restore_workspace
from studyflow.modules.workspace.repository import validate_backup
from studyflow.shared.domain import DomainError
from .. import runtime
from ..runtime import output, fail
from ..registry import snapshot_app, workspace_app


@workspace_app.command("export")
def workspace_export(
    output_path: Path = typer.Option(..., "--output", help="导出的 .zip 或 .studyflow 文件路径。"),
    format: str = typer.Option("text", "--format"),
) -> None:
    """以 SQLite 一致性快照导出工作区及其 Markdown 文件。"""
    try:
        settings = Settings.from_env()
        settings.ensure_layout()
        output({"ok": True, **export_workspace(settings, output_path)}, format)
    except Exception as exc:
        fail(exc)

@workspace_app.command("purge-courses")
def workspace_purge_courses(
    dry_run: bool = typer.Option(False, "--dry-run", help="只盘点课程及其关联数据，不执行删除。"),
    confirm: bool = typer.Option(False, "--confirm", help="确认删除课程及其专属数据。"),
    backup: Path | None = typer.Option(None, "--backup", exists=True, readable=True, help="已通过 workspace export 导出的备份文件。执行删除时必填。"),
    format: str = typer.Option("text", "--format"),
) -> None:
    """受控清理课程数据；保留计划线、数据库结构和工作区配置。"""
    if dry_run and confirm:
        fail(DomainError("INVALID_ARGUMENT", "--dry-run 与 --confirm 不能同时使用。", "先使用 --dry-run 查看清单，再单独执行确认清理。"))
    if not dry_run and not confirm:
        fail(DomainError("CONFIRMATION_REQUIRED", "未执行清理：必须显式使用 --dry-run 或 --confirm。", "先运行 workspace purge-courses --dry-run --format json。"))
    try:
        service = runtime.service(read_only=dry_run)
        if dry_run:
            output({"ok": True, "mode": "dry-run", **service.preview_course_purge()}, format)
            return
        if backup is None:
            raise DomainError("BACKUP_REQUIRED", "确认清理必须提供已导出的备份文件。", "先运行 workspace export --output <backup.zip>，再传入 --backup。")
        checked = validate_backup(backup)
        output({"ok": True, "mode": "purge", "backup": checked, **service.purge_courses(confirm=True)}, format)
    except Exception as exc:
        fail(exc)

@workspace_app.command("import")
def workspace_import(
    archive_path: Path = typer.Option(..., "--file", exists=True, readable=True, help="StudyFlow 工作区备份文件。"),
    target_root: Path = typer.Option(..., "--target", help="新的工作区目录；已有目录会先改名保留。"),
    format: str = typer.Option("text", "--format"),
) -> None:
    """校验备份后导入到 staging，再原子切换工作区目录。"""
    try:
        output({"ok": True, **restore_workspace(archive_path, target_root)}, format)
    except Exception as exc:
        fail(exc)

@snapshot_app.command("generate")
def snapshot_generate(scope: str = typer.Option("today", "--scope"), format: str = typer.Option("text", "--format")) -> None:
    try:
        snap = runtime.service().generate_snapshot(scope=scope)
        output({"ok": True, "snapshot_id": snap.id, "path": snap.relative_path}, format)
    except Exception as exc:
        fail(exc)

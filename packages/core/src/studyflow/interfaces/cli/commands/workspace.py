from __future__ import annotations
from pathlib import Path
import typer
from studyflow.config import Settings
from studyflow.workspace import export_workspace, restore_workspace
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
        output(export_workspace(settings, output_path), format)
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
        output(restore_workspace(archive_path, target_root), format)
    except Exception as exc:
        fail(exc)

@snapshot_app.command("generate")
def snapshot_generate(scope: str = typer.Option("today", "--scope"), format: str = typer.Option("text", "--format")) -> None:
    try:
        snap = runtime.service().generate_snapshot(scope=scope)
        output({"ok": True, "snapshot_id": snap.id, "path": snap.relative_path}, format)
    except Exception as exc:
        fail(exc)

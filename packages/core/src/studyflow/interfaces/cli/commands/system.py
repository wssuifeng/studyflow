from __future__ import annotations
import platform
from datetime import date
import typer
from studyflow import __version__
from studyflow.config import Settings
from studyflow.seed import seed
from studyflow.migrations import upgrade_sqlite
from .. import runtime
from ..runtime import _workspace_summary, _database_diagnostic, _discovery_metadata, _dashboard_payload, output, fail, PROTOCOL_VERSION, CAPABILITIES
from ..registry import app


@app.command("db-upgrade")
def db_upgrade(format: str = typer.Option("text", "--format")) -> None:
    """对空库或完整旧 SQLite 执行受控 Alembic 升级；未知或不完整结构会安全失败。"""
    try:
        result = upgrade_sqlite(Settings.from_env())
        output({"ok": True, **result}, format)
    except Exception as exc:
        fail(exc)

@app.command()
def init() -> None:
    """初始化数据库表并写入一条可学习的演示课程。"""
    try:
        result = seed()
        output({"ok": True, **result})
    except Exception as exc:
        fail(exc)

def _dashboard_command(date_value: str | None, plan_line_id: str | None, task_kind: str | None, format: str) -> None:
    try:
        target_date = date.fromisoformat(date_value) if date_value else date.today()
        settings = Settings.from_env()
        data = runtime.service().dashboard(target_date, plan_line_id=plan_line_id, task_kind=task_kind)
        output(_dashboard_payload(data, target_date, settings), format)
    except Exception as exc:
        fail(exc)

@app.command()
def status(date_value: str = typer.Option(None, "--date"), plan_line_id: str | None = typer.Option(None, "--plan-line"), task_kind: str | None = typer.Option(None, "--kind"), format: str = typer.Option("text", "--format")) -> None:
    """查看指定日期的 StudyFlow 学习控制台摘要。"""
    _dashboard_command(date_value, plan_line_id, task_kind, format)

@app.command()
def today(date_value: str = typer.Option(None, "--date"), plan_line_id: str | None = typer.Option(None, "--plan-line"), task_kind: str | None = typer.Option(None, "--kind"), format: str = typer.Option("text", "--format")) -> None:
    """提供 Agent 中立的今日/指定日期学习摘要。"""
    _dashboard_command(date_value, plan_line_id, task_kind, format)

@app.command()
def version(format: str = typer.Option("text", "--format")) -> None:
    """输出应用版本与 CLI 协议版本。"""
    settings = Settings.from_env()
    output({
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "app_version": __version__,
        "python_version": platform.python_version(),
        **_discovery_metadata(settings),
        "capabilities": [item["name"] for item in CAPABILITIES],
        "next_action": "运行 studyflow doctor --format json 检查工作区和数据库。",
    }, format)

@app.command()
def capabilities(format: str = typer.Option("text", "--format")) -> None:
    """输出当前 CLI 可发现能力；不连接数据库，不执行写操作。"""
    settings = Settings.from_env()
    output({
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "app_version": __version__,
        **_discovery_metadata(settings),
        "capabilities": CAPABILITIES,
        "next_action": "运行 studyflow doctor --format json，再按当前任务选择能力。",
    }, format)

@app.command()
def doctor(format: str = typer.Option("text", "--format")) -> None:
    """诊断工作区与数据库连接，不暴露数据库密码。"""
    try:
        settings = Settings.from_env()
        workspace = _workspace_summary(settings)
        database = _database_diagnostic(settings)
        healthy = bool(workspace["exists"] and database["status"] in {"ready", "not_initialized"})
        output({
            "ok": True,
            "protocol_version": PROTOCOL_VERSION,
            "workspace": workspace,
            "database": database,
            "capabilities": [item["name"] for item in CAPABILITIES],
            "healthy": healthy,
            "next_action": database.get("next_action") or ("运行 studyflow today --format json 查看今日学习。" if healthy else "检查工作区路径和环境变量。"),
        }, format)
    except Exception as exc:
        fail(exc)

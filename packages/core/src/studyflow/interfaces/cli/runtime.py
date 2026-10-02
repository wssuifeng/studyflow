from __future__ import annotations
import json
import platform
import sys
from datetime import date
from pathlib import Path
from typing import Any
from sqlalchemy import inspect, text as sql_text
from sqlalchemy.engine import make_url
import typer
from studyflow import __version__
from studyflow.config import Settings
from studyflow.db import build_engine, build_session_factory, init_db
from studyflow.domain import DomainError
from studyflow.seed import seed
from studyflow.migrations import upgrade_sqlite
from studyflow.services import AppService
from studyflow.workspace import export_workspace, restore_workspace
from .registry import app

PROTOCOL_VERSION = "1.2"

CAPABILITIES = [
    {"name": "plan_detail", "command": "studyflow plan detail --id <id> --format json", "kind": "read"},
    {"name": "document_read", "command": "studyflow document read --path <path> --format json", "kind": "read"},
    {"name": "version", "command": "studyflow version --format json", "kind": "read"},
    {"name": "capabilities", "command": "studyflow capabilities --format json", "kind": "read"},
    {"name": "doctor", "command": "studyflow doctor --format json", "kind": "diagnostic"},
    {"name": "today", "command": "studyflow today --format json", "kind": "read"},
    {"name": "assignment_queue", "command": "studyflow assignment queue --format json", "kind": "read"},
    {"name": "course_import", "command": "studyflow course import --file <path> --format json", "kind": "write"},
    {"name": "course_answers_get", "command": "studyflow course answers get --id <course-id> --format json", "kind": "read"},
    {"name": "course_answers_save", "command": "studyflow course answers save --id <course-id> --file <answers.json> --idempotency-key <key> --format json", "kind": "write"},
    {"name": "course_answers_submit", "command": "studyflow course answers submit --id <course-id> --file <answers.json> --idempotency-key <key> --format json", "kind": "write"},
    {"name": "course_study_open", "command": "studyflow course study-open --id <course-id> --idempotency-key <key> --format json", "kind": "write"},
    {"name": "course_study_get", "command": "studyflow course study-detail --study-id <study-id> --format json", "kind": "read"},
    {"name": "course_detail", "command": "studyflow course detail --id <course-id> --format json", "kind": "read"},
    {"name": "submission_get", "command": "studyflow submission get --id <submission-id> --format json", "kind": "read"},
    {"name": "review_write", "command": "studyflow review write --submission <id> --summary <text> --decision <decision> --format json", "kind": "write"},
    {"name": "submission_revise", "command": "studyflow submission revise --parent <id> --file <path> --format json", "kind": "write"},
    {"name": "submission_retest", "command": "studyflow submission retest --parent <id> --file <path> --format json", "kind": "write"},
    {"name": "snapshot_generate", "command": "studyflow snapshot generate --format json", "kind": "write"},
    {"name": "workspace_export", "command": "studyflow workspace export --output <backup.zip> --format json", "kind": "write"},
    {"name": "workspace_import", "command": "studyflow workspace import --file <backup.zip> --target <workspace-dir> --format json", "kind": "write"},
]

def _configure_utf8_stdio() -> None:
    """让 Windows 终端和管道都以 UTF-8 输出，避免 Agent 读取中文 JSON 时乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (RuntimeError, ValueError):
            # 测试运行器或被替换的流可能不允许重新配置；不影响 CLI 主逻辑。
            continue

def _database_url_without_password(database_url: str) -> str:
    """返回诊断安全的数据库 URL，绝不暴露数据库密码。"""
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        if "://" not in database_url:
            return database_url
        scheme, remainder = database_url.split("://", 1)
        if "@" in remainder and ":" in remainder.split("@", 1)[0]:
            credentials, host = remainder.split("@", 1)
            user = credentials.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return database_url

def _is_writable(path: Path) -> bool:
    probe = path / ".studyflow-write-check"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False

def _workspace_summary(settings: Settings) -> dict[str, Any]:
    root = settings.workspace_root
    governance_root = root if (root / "docs" / "00_总控.md").is_file() else root.parent
    governance_files = [
        "00-AI主控提示词.md",
        "02-当前阶段执行看板.md",
        "03-文档索引库.md",
        "04-AI上下文快照.md",
        "docs/00_总控.md",
    ]
    present = {relative: (governance_root / relative).is_file() for relative in governance_files}
    return {
        "root": str(root),
        "governance_root": str(governance_root),
        "exists": root.is_dir(),
        "writable": root.is_dir() and _is_writable(root),
        "governance_files": present,
        "governance_ready": all(present.values()),
        "content_root": str(settings.content_root),
    }

def _database_diagnostic(settings: Settings) -> dict[str, Any]:
    database_url = settings.database_url
    safe_url = _database_url_without_password(database_url)
    try:
        parsed = make_url(database_url)
        driver = parsed.drivername
    except Exception:
        parsed = None
        driver = "unknown"

    result: dict[str, Any] = {
        "url": safe_url,
        "driver": driver,
        "managed_by_app": driver.startswith("sqlite"),
        "status": "unknown",
        "reachable": False,
        "required_tables": {},
    }
    if driver.startswith("sqlite") and parsed is not None:
        db_path = Path(parsed.database or "")
        if not db_path.is_absolute():
            db_path = (Path.cwd() / db_path).resolve()
        result["path"] = str(db_path)
        if not db_path.exists():
            result["status"] = "not_initialized"
            result["next_action"] = "运行 studyflow init 初始化本地数据库。"
            return result

    engine = None
    try:
        engine = build_engine(settings)
        with engine.connect() as connection:
            connection.execute(sql_text("SELECT 1"))
            tables = set(inspect(connection).get_table_names())
        required = ["plan_lines", "courses", "exercises", "submissions"]
        missing = [table for table in required if table not in tables]
        result["required_tables"] = {table: table in tables for table in required}
        result["reachable"] = True
        result["status"] = "ready" if not missing else "incomplete"
        result["next_action"] = "" if not missing else "运行 studyflow db-upgrade 或 studyflow init。"
    except Exception:
        result["status"] = "unavailable"
        result["next_action"] = "检查数据库配置后运行 studyflow doctor --format json。"
    finally:
        if engine is not None:
            engine.dispose()
    return result

def _unchecked_database_summary(settings: Settings) -> dict[str, Any]:
    try:
        parsed = make_url(settings.database_url)
        driver = parsed.drivername
    except Exception:
        driver = "unknown"
    return {
        "url": _database_url_without_password(settings.database_url),
        "driver": driver,
        "managed_by_app": driver.startswith("sqlite"),
        "status": "not_checked",
        "reachable": None,
    }

def _discovery_metadata(settings: Settings) -> dict[str, Any]:
    root = settings.workspace_root
    return {
        "workspace": {
            "root": str(root),
            "exists": root.is_dir(),
        },
        "database": _unchecked_database_summary(settings),
    }

def _dashboard_payload(data: dict[str, Any], target_date: date, settings: Settings | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "date": target_date,
        "primary_task": data["primary_task"].title if data["primary_task"] else None,
        "current_course": {
            "id": data["current_course"].id,
            "title": data["current_course"].title,
            "sequence": data["course_position"],
            "total": data["course_total"],
        } if data["current_course"] else None,
        "courses": [
            {
                "id": course.id,
                "title": course.title,
                "sequence": course.plan_sequence,
                "total": course.plan_total,
                "knowledge_total": course.knowledge_total,
                "knowledge_completed": course.knowledge_completed,
                "progress_percent": course.progress_percent,
            }
            for course in data["courses"]
        ],
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "kind": task.task_kind,
                "plan_line": task.plan_line.name if task.plan_line else None,
            }
            for task in data["tasks"]
        ],
        "queue_counts": data["queue_counts"],
        "next_action": "优先打开 current_course，或处理 assignment queue 中的待批改作答。",
        **(_discovery_metadata(settings) if settings else {}),
        "capabilities": [item["name"] for item in CAPABILITIES],
    }

def service() -> AppService:
    settings = Settings.from_env()
    settings.ensure_layout()
    engine = build_engine(settings)
    init_db(engine)
    return AppService(settings, build_session_factory(engine))

def output(payload: Any, format: str = "text") -> None:
    if format == "json":
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    else:
        if isinstance(payload, dict):
            for key, value in payload.items():
                typer.echo(f"{key}: {value}")
        else:
            typer.echo(payload)

def _safe_error_message(error: Exception) -> str:
    message = str(error)
    for token in ("mysql+pymysql://", "mysql://", "postgresql://", "sqlite:///"):
        if token in message:
            prefix, remainder = message.split(token, 1)
            message = prefix + _database_url_without_password(token + remainder)
            break
    return message

def fail(error: Exception) -> None:
    if isinstance(error, DomainError):
        payload = {"ok": False, "error_code": error.code, "message": error.message, "next_action": error.next_action}
    else:
        payload = {"ok": False, "error_code": "INTERNAL_ERROR", "message": _safe_error_message(error), "next_action": "查看命令参数或运行日志"}
    # 错误输出保持结构化 JSON，便于任意 Agent/脚本稳定解析；人类可读信息仍包含在 message 字段中。
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str), err=True)
    raise typer.Exit(code=1)

_configure_utf8_stdio()

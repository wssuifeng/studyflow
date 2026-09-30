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

from . import __version__
from .config import Settings
from .db import build_engine, build_session_factory, init_db
from .domain import DomainError
from .seed import seed
from .migrations import upgrade_sqlite
from .services import AppService
from .workspace import export_workspace, restore_workspace

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


_configure_utf8_stdio()


app = typer.Typer(help="StudyFlow 本地学习工作台 CLI")
plan_app = typer.Typer(help="计划与任务")
course_app = typer.Typer(help="课程")
course_answers_app = typer.Typer(help="整课草稿与统一提交")
course_app.add_typer(course_answers_app, name="answers")
submission_app = typer.Typer(help="作答")
review_app = typer.Typer(help="批改")
document_app = typer.Typer(help="文档")
snapshot_app = typer.Typer(help="上下文快照")
task_app = typer.Typer(help="任务")
assignment_app = typer.Typer(help="外部 Agent 待处理队列")
workspace_app = typer.Typer(help="工作区导出与恢复")
app.add_typer(plan_app, name="plan")
app.add_typer(course_app, name="course")
app.add_typer(submission_app, name="submission")
app.add_typer(review_app, name="review")
app.add_typer(document_app, name="document")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(task_app, name="task")
app.add_typer(assignment_app, name="assignment")
app.add_typer(workspace_app, name="workspace")


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
    {"name": "course_detail", "command": "studyflow course detail --id <course-id> --format json", "kind": "read"},
    {"name": "submission_get", "command": "studyflow submission get --id <submission-id> --format json", "kind": "read"},
    {"name": "review_write", "command": "studyflow review write --submission <id> --summary <text> --decision <decision> --format json", "kind": "write"},
    {"name": "submission_revise", "command": "studyflow submission revise --parent <id> --file <path> --format json", "kind": "write"},
    {"name": "submission_retest", "command": "studyflow submission retest --parent <id> --file <path> --format json", "kind": "write"},
    {"name": "snapshot_generate", "command": "studyflow snapshot generate --format json", "kind": "write"},
    {"name": "workspace_export", "command": "studyflow workspace export --output <backup.zip> --format json", "kind": "write"},
    {"name": "workspace_import", "command": "studyflow workspace import --file <backup.zip> --target <workspace-dir> --format json", "kind": "write"},
]


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




@app.command("db-upgrade")
def db_upgrade(format: str = typer.Option("text", "--format")) -> None:
    """对空库或完整旧 SQLite 执行受控 Alembic 升级；未知或不完整结构会安全失败。"""
    try:
        result = upgrade_sqlite(Settings.from_env())
        output({"ok": True, **result}, format)
    except Exception as exc:
        fail(exc)


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


@app.command()
def init() -> None:
    """初始化数据库表并写入一条可学习的演示课程。"""
    try:
        result = seed()
        output({"ok": True, **result})
    except Exception as exc:
        fail(exc)


@plan_app.command("list")
def plan_list(format: str = typer.Option("text", "--format")) -> None:
    try:
        rows = service().list_plan_lines()
        output({"ok": True, "plans": [{"id": row.id, "name": row.name, "priority": row.priority, "status": row.status} for row in rows]}, format)
    except Exception as exc:
        fail(exc)


@plan_app.command("create")
def plan_create(name: str = typer.Option(..., "--name"), priority: int = typer.Option(1, "--priority"), format: str = typer.Option("text", "--format")) -> None:
    try:
        row = service().create_plan_line(name, priority)
        output({"ok": True, "id": row.id, "name": row.name, "priority": row.priority, "status": row.status}, format)
    except Exception as exc:
        fail(exc)


def _task_list(date_value: str | None, plan_line_id: str | None, task_kind: str | None, format: str) -> None:
    try:
        target = date.fromisoformat(date_value) if date_value else None
        rows = service().list_tasks(target, plan_line_id, task_kind)
        output({"ok": True, "tasks": [{"id": row.id, "title": row.title, "date": row.scheduled_date, "status": row.status, "kind": row.task_kind, "plan_line": row.plan_line.name if row.plan_line else None} for row in rows]}, format)
    except Exception as exc:
        fail(exc)


@plan_app.command("task-list")
def plan_task_list(date_value: str | None = typer.Option(None, "--date"), plan_line_id: str | None = typer.Option(None, "--plan-line"), task_kind: str | None = typer.Option(None, "--kind"), format: str = typer.Option("text", "--format")) -> None:
    _task_list(date_value, plan_line_id, task_kind, format)


@task_app.command("list")
def task_list(date_value: str | None = typer.Option(None, "--date"), plan_line_id: str | None = typer.Option(None, "--plan-line"), task_kind: str | None = typer.Option(None, "--kind"), format: str = typer.Option("text", "--format")) -> None:
    _task_list(date_value, plan_line_id, task_kind, format)


def _task_create(title: str, date_value: str, task_kind: str, plan_line_id: str | None, description: str, priority: int, format: str) -> None:
    try:
        row = service().create_task(title, date.fromisoformat(date_value), task_kind, description, plan_line_id=plan_line_id, priority=priority)
        output({"ok": True, "id": row.id, "title": row.title, "date": row.scheduled_date, "kind": row.task_kind, "plan_line_id": row.plan_line_id}, format)
    except Exception as exc:
        fail(exc)


@plan_app.command("task-create")
def plan_task_create(title: str = typer.Option(..., "--title"), date_value: str = typer.Option(..., "--date"), task_kind: str = typer.Option("OTHER", "--kind"), plan_line_id: str | None = typer.Option(None, "--plan-line"), description: str = typer.Option("", "--description"), priority: int = typer.Option(1, "--priority"), format: str = typer.Option("text", "--format")) -> None:
    _task_create(title, date_value, task_kind, plan_line_id, description, priority, format)


@task_app.command("create")
def task_create(title: str = typer.Option(..., "--title"), date_value: str = typer.Option(..., "--date"), task_kind: str = typer.Option("OTHER", "--kind"), plan_line_id: str | None = typer.Option(None, "--plan-line"), description: str = typer.Option("", "--description"), priority: int = typer.Option(1, "--priority"), format: str = typer.Option("text", "--format")) -> None:
    _task_create(title, date_value, task_kind, plan_line_id, description, priority, format)


def _dashboard_command(date_value: str | None, plan_line_id: str | None, task_kind: str | None, format: str) -> None:
    try:
        target_date = date.fromisoformat(date_value) if date_value else date.today()
        settings = Settings.from_env()
        data = service().dashboard(target_date, plan_line_id=plan_line_id, task_kind=task_kind)
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


@course_app.command("list")
def course_list(plan_line_id: str | None = typer.Option(None, "--plan-line"), format: str = typer.Option("text", "--format")) -> None:
    try:
        rows = service().list_courses(plan_line_id)
        output({"ok": True, "courses": [{"id": row.id, "title": row.title, "summary": row.summary, "subject": row.subject, "content_type": row.content_type, "difficulty": row.difficulty, "source_type": row.source_type, "plan_line": row.plan_line.name if row.plan_line else None} for row in rows]}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("detail")
def course_detail(course_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    """读取课程、多知识点、阅读进度及作答状态。"""
    try:
        output({"ok": True, **service().course_detail(course_id)}, format)
    except Exception as exc:
        fail(exc)


@plan_app.command("detail")
def plan_detail(plan_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    try:
        output({"ok": True, **service().plan_detail(plan_id)}, format)
    except Exception as exc:
        fail(exc)


@submission_app.command("get")
def submission_get(submission_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    try:
        output({"ok": True, "submission": service().submission_detail(submission_id)}, format)
    except Exception as exc:
        fail(exc)


@document_app.command("read")
def document_read(path: str = typer.Option(..., "--path"), format: str = typer.Option("text", "--format")) -> None:
    try:
        output({"ok": True, **service().read_document(path)}, format)
    except Exception as exc:
        fail(exc)


@course_app.command("import")
def course_import(file_path: Path = typer.Option(..., "--file", exists=True, readable=True), format: str = typer.Option("text", "--format")) -> None:
    try:
        result = service().import_course_markdown(file_path)
        output({"ok": True, **result}, format)
    except Exception as exc:
        fail(exc)


@submission_app.command("list-pending")
def submission_pending(format: str = typer.Option("text", "--format")) -> None:
    try:
        queue = service().agent_queue()
        output({"ok": True, "submissions": queue["waiting_review"], "queue": queue}, format)
    except Exception as exc:
        fail(exc)


@assignment_app.command("queue")
def assignment_queue(plan_line_id: str | None = typer.Option(None, "--plan-line"), format: str = typer.Option("text", "--format")) -> None:
    """列出等待批改、修正或复测的统一 Agent 队列。"""
    try:
        output({"ok": True, **service().agent_queue(plan_line_id)}, format)
    except Exception as exc:
        fail(exc)


@submission_app.command("revise")
def submission_revise(parent_submission: str = typer.Option(..., "--parent"), answer_file: Path = typer.Option(..., "--file", exists=True, readable=True), idempotency_key: str | None = typer.Option(None, "--idempotency-key"), format: str = typer.Option("text", "--format")) -> None:
    """基于需要修正的作答创建不可覆盖的修正版。"""
    try:
        submission = service().revise_submission(parent_submission, answer_file.read_text(encoding="utf-8"), idempotency_key=idempotency_key, source="AGENT_CLI")
        output({"ok": True, "submission_id": submission.id, "parent_submission_id": submission.parent_submission_id, "attempt_number": submission.attempt_number, "attempt_kind": submission.attempt_kind, "status": submission.status, "source": submission.source, "next_action": submission.next_action}, format)
    except Exception as exc:
        fail(exc)


@submission_app.command("retest")
def submission_retest(parent_submission: str = typer.Option(..., "--parent"), answer_file: Path = typer.Option(..., "--file", exists=True, readable=True), idempotency_key: str | None = typer.Option(None, "--idempotency-key"), format: str = typer.Option("text", "--format")) -> None:
    """基于要求复测的作答创建不可覆盖的复测版。"""
    try:
        submission = service().retest_submission(parent_submission, answer_file.read_text(encoding="utf-8"), idempotency_key=idempotency_key, source="AGENT_CLI")
        output({"ok": True, "submission_id": submission.id, "parent_submission_id": submission.parent_submission_id, "attempt_number": submission.attempt_number, "attempt_kind": submission.attempt_kind, "status": submission.status, "source": submission.source, "next_action": submission.next_action}, format)
    except Exception as exc:
        fail(exc)


@review_app.command("write")
def review_write(submission_id: str = typer.Option(..., "--submission"), summary: str = typer.Option(..., "--summary"), detail_file: Path | None = typer.Option(None, "--file"), issue_count: int = typer.Option(0, "--issue-count"), needs_revision: bool = typer.Option(False, "--needs-revision"), decision: str | None = typer.Option(None, "--decision", help="PASSED / REVISION_REQUIRED / RETEST_REQUIRED"), next_action: str = typer.Option("", "--next-action"), idempotency_key: str | None = typer.Option(None, "--idempotency-key"), format: str = typer.Option("text", "--format")) -> None:
    try:
        detail = detail_file.read_text(encoding="utf-8") if detail_file else ""
        review = service().write_review(submission_id, summary, detail, issue_count, needs_revision, idempotency_key, decision=decision, next_action=next_action)
        output({"ok": True, "review_id": review.id, "submission_id": review.submission_id, "decision": review.decision, "next_action": review.next_action, "needs_revision": review.needs_revision}, format)
    except Exception as exc:
        fail(exc)


@document_app.command("check")
def document_check(relative_path: str = typer.Option(..., "--path"), format: str = typer.Option("text", "--format")) -> None:
    try:
        doc = service().check_document(relative_path)
        output({"ok": True, "id": doc.id, "path": doc.relative_path, "status": doc.status, "size": doc.file_size}, format)
    except Exception as exc:
        fail(exc)


@snapshot_app.command("generate")
def snapshot_generate(scope: str = typer.Option("today", "--scope"), format: str = typer.Option("text", "--format")) -> None:
    try:
        snap = service().generate_snapshot(scope=scope)
        output({"ok": True, "snapshot_id": snap.id, "path": snap.relative_path}, format)
    except Exception as exc:
        fail(exc)



@course_answers_app.command("get")
def course_answers_get(course_id: str = typer.Option(..., "--id"), format: str = typer.Option("text", "--format")) -> None:
    """读取本课原答案、草稿、批改和后续行动。"""
    try:
        output({"ok": True, **service().course_answer_sheet(course_id)}, format)
    except Exception as exc:
        fail(exc)


def _write_course_answers_file(course_id: str, file: Path, key: str, operation: str, format: str) -> None:
    try:
        payload = json.loads(file.read_text(encoding="utf-8-sig"))
        answers = payload.get("answers") if isinstance(payload, dict) else payload
        result = service().write_course_answers(course_id, answers, operation, key, source="AGENT_CLI")
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


if __name__ == "__main__":
    app()

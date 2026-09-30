from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .config import Settings
from .domain import DomainError


def _alembic_config(settings: Settings):
    from alembic.config import Config

    candidates = [Path(__file__).resolve().parents[1]]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.insert(0, Path(frozen_root))
    project_root = next((root for root in candidates if (root / "alembic.ini").exists() and (root / "migrations").is_dir()), None)
    if project_root is None:
        raise DomainError("MIGRATION_CONFIG_MISSING", "找不到 Alembic 配置文件。", "确认 StudyFlow Engine 包含 alembic.ini 和 migrations/ 目录。")
    config_path = project_root / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.attributes["studyflow_database_url"] = settings.database_url
    return config


def _alembic_upgrade(settings: Settings) -> None:
    """Run the checked-in Alembic chain against the explicit application URL."""
    from alembic import command

    command.upgrade(_alembic_config(settings), "head")


def _alembic_stamp(settings: Settings, revision: str = "0003_learning_console_lifecycle") -> None:
    """Record a known legacy schema revision before applying newer additive migrations."""
    from alembic import command

    command.stamp(_alembic_config(settings), revision)


LEGACY_TABLES = {
    "plan_lines", "stages", "tasks", "time_blocks", "courses", "lessons",
    "exercises", "submissions", "review_feedback", "documents",
    "context_snapshots", "event_logs",
}
CONSOLE_TABLES = {"plan_course_items", "course_schedule_items"}
CURRENT_REVISION = "0005_course_answers"
GENERAL_COLUMNS = {
    "tasks": {"plan_line_id", "task_kind", "course_schedule_item_id"},
    "courses": {"subject", "content_type", "difficulty", "source_type"},
    "exercises": {"exercise_type"},
    "submissions": {"parent_submission_id", "attempt_number", "attempt_kind", "next_action"},
    "review_feedback": {"decision", "next_action"},
}

def _sqlite_path(settings: Settings) -> Path | None:
    url = settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    raw = url[len(prefix):]
    path = Path(raw)
    if not path.is_absolute():
        path = (settings.workspace_root / path).resolve()
    return path


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}



def backup_sqlite(settings: Settings) -> Path | None:
    source = _sqlite_path(settings)
    if source is None or not source.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    target = source.with_name(f"{source.stem}.backup-{stamp}{source.suffix}")
    # SQLite's backup API includes committed WAL content and provides a consistent
    # snapshot even if another connection has the database open.
    with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
        source_connection.backup(target_connection)
    return target


def upgrade_sqlite(settings: Settings) -> dict[str, str | bool | None]:
    """Explicitly upgrade an empty or complete legacy SQLite database with Alembic.

    The command is deliberately conservative: a partial/unknown schema fails closed;
    a recognized database is backed up before any mutation.
    """
    path = _sqlite_path(settings)
    if path is None:
        raise DomainError("UNSUPPORTED_DATABASE", "自动升级目前只支持 SQLite；MySQL 请使用 Alembic 命令并先完成备份。", "为目标数据库执行 alembic upgrade head。")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if not tables:
            connection.close()
            _alembic_upgrade(settings)
            return {"upgraded": True, "status": "FRESH_DATABASE_MIGRATED", "backup": None}

        legacy_tables = LEGACY_TABLES & tables
        if legacy_tables and not LEGACY_TABLES.issubset(tables):
            raise DomainError("PARTIAL_SCHEMA_UNSUPPORTED", "检测到不完整或未知的旧 schema，已停止自动升级。", "先备份数据库并人工确认表结构，再执行 Alembic 迁移。")
        if not legacy_tables:
            raise DomainError("UNKNOWN_SCHEMA", "检测到未知数据库结构，已停止自动升级。", "使用独立数据库或人工编写迁移。")

        missing_general = any(column not in _columns(connection, table) for table, columns in GENERAL_COLUMNS.items() for column in columns)
        has_version_table = "alembic_version" in tables
        version_row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone() if has_version_table and _columns(connection, "alembic_version") else None
        version = version_row[0] if version_row else None
        missing_console_tables = not CONSOLE_TABLES.issubset(tables)
        has_progress_table = "learning_progress" in tables
        progress_columns = _columns(connection, "learning_progress") if has_progress_table else set()
        required_progress_columns = {"id", "course_id", "lesson_id", "progress_percent", "status", "last_position", "source", "created_at", "updated_at"}
        if has_version_table and version in {"0004_learning_progress", CURRENT_REVISION}:
            if not has_progress_table or not required_progress_columns.issubset(progress_columns) or "submission_write_receipts" not in tables:
                raise DomainError("SCHEMA_REVISION_MISMATCH", "数据库标记为当前迁移版本，但 learning_progress 表结构不完整。", "先备份数据库并人工核对 schema，禁止自动跳过或重建用户进度数据。")
            if version == CURRENT_REVISION and "course_write_receipts" not in tables:
                raise DomainError("SCHEMA_REVISION_MISMATCH", "当前迁移版本的课程写入凭据表缺失。", "先备份并人工核对 schema，禁止覆盖学习数据。")
            if version == CURRENT_REVISION and not missing_general and not missing_console_tables:
                return {"upgraded": False, "status": "ALREADY_CURRENT", "backup": None}

        connection.close()
        backup = backup_sqlite(settings)
        if not missing_general and not missing_console_tables and version is None:
            _alembic_stamp(settings, "0003_learning_console_lifecycle")
            _alembic_upgrade(settings)
            status = "LEGACY_STAMPED_UPGRADED"
        else:
            _alembic_upgrade(settings)
            status = "LEGACY_UPGRADED"
        return {"upgraded": True, "status": status, "backup": str(backup) if backup else None}
    finally:
        try:
            connection.close()
        except Exception:
            pass

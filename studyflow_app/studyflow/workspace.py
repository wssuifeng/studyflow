from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from .config import Settings
from .domain import DomainError

WORKSPACE_FORMAT_VERSION = "1"
DATABASE_ARCHIVE_PATH = "database/studyflow.db"
SUPPORTED_SCHEMA_REVISIONS = {
    "UNSTAMPED",
    "0001_mvp_baseline",
    "0002_generic_metadata",
    "0003_learning_console_lifecycle",
    "0004_learning_progress",
    "0005_course_answers",
}
REQUIRED_DATABASE_TABLES = {
    "plan_lines",
    "courses",
    "lessons",
    "exercises",
    "submissions",
    "review_feedback",
    "documents",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str, *, field: str = "relative_path") -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError("BACKUP_PATH_INVALID", f"备份中的 {field} 必须是非空相对路径。", "修正 manifest 后重新导出。")
    raw = value.strip()
    if "\\" in raw or PureWindowsPath(raw).is_absolute() or raw.startswith("/"):
        raise DomainError("BACKUP_PATH_INVALID", f"备份中的 {field} 不是安全的 POSIX 相对路径：{raw}", "只使用工作区内的正斜杠相对路径。")
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise DomainError("BACKUP_PATH_INVALID", f"备份中的 {field} 越过了工作区边界：{raw}", "移除绝对路径、盘符和 .. 路径段。")
    return PurePosixPath(*parts).as_posix()


def _safe_archive_member(name: str) -> str:
    return _safe_relative(name, field="archive member")


def _workspace_file(root: Path, relative_path: str) -> Path:
    normalized = _safe_relative(relative_path)
    candidate = (root / Path(*PurePosixPath(normalized).parts)).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise DomainError("BACKUP_PATH_INVALID", f"文件越过工作区边界：{relative_path}", "只允许工作区内相对路径。")
    return candidate


def _schema_revision(database_path: Path) -> tuple[str, set[str]]:
    try:
        connection = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        raise DomainError("DATABASE_UNREADABLE", "备份中的 SQLite 数据库无法打开。", "确认数据库文件完整后重新导出。") from exc
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        missing = sorted(REQUIRED_DATABASE_TABLES - tables)
        if missing:
            raise DomainError("UNKNOWN_SCHEMA", f"SQLite schema 缺少必要表：{', '.join(missing)}", "使用完整 StudyFlow 工作区重新导出。")
        if "alembic_version" not in tables:
            revision = "UNSTAMPED"
        else:
            versions = [row[0] for row in connection.execute("SELECT version_num FROM alembic_version").fetchall()]
            if len(versions) != 1 or versions[0] not in SUPPORTED_SCHEMA_REVISIONS:
                value = ", ".join(str(item) for item in versions) or "空"
                raise DomainError("UNKNOWN_SCHEMA", f"不支持的 SQLite schema 版本：{value}", "先完成受控迁移，再导出工作区。")
            revision = versions[0]
        return revision, tables
    finally:
        connection.close()


def _document_paths(settings: Settings, database_path: Path) -> list[str]:
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute("SELECT relative_path FROM documents ORDER BY relative_path").fetchall()
    finally:
        connection.close()
    paths = {_safe_relative(row[0], field="document.relative_path") for row in rows}
    if settings.content_root.exists():
        for path in settings.content_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
                if path.is_symlink():
                    raise DomainError("WORKSPACE_SYMLINK_UNSUPPORTED", f"Markdown 文件不能是符号链接：{path}", "将文件复制到工作区后重新导出。")
                paths.add(path.relative_to(settings.workspace_root).as_posix())
    return sorted(paths)


def _snapshot_sqlite(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.execute("PRAGMA busy_timeout=10000")
        source_connection.backup(target_connection)
    except sqlite3.Error as exc:
        raise DomainError("BACKUP_DATABASE_FAILED", "SQLite 一致性备份失败，未生成可用导出。", "关闭正在写入数据库的进程后重试。") from exc
    finally:
        target_connection.close()
        source_connection.close()


def export_workspace(settings: Settings, archive_path: str | Path) -> dict[str, Any]:
    """Export a consistent SQLite snapshot and its referenced Markdown files."""
    database_path = settings.database_path
    if database_path is None:
        raise DomainError("UNSUPPORTED_DATABASE", "工作区导出目前只支持 SQLite。", "为服务端数据库使用独立备份流程，不要把 MySQL 当作桌面导出源。")
    if not database_path.exists():
        raise DomainError("DATABASE_NOT_FOUND", "工作区数据库不存在，无法导出。", "先运行 studyflow init 或启动一次桌面工作区。")
    revision, _ = _schema_revision(database_path)
    relative_files = _document_paths(settings, database_path)
    source_files: list[tuple[str, Path]] = []
    for relative_path in relative_files:
        source = _workspace_file(settings.workspace_root, relative_path)
        if not source.exists() or not source.is_file():
            raise DomainError("DOCUMENT_MISSING", f"工作区缺少已登记 Markdown：{relative_path}", "补回文件后重新导出，避免生成不完整备份。")
        if source.is_symlink():
            raise DomainError("WORKSPACE_SYMLINK_UNSUPPORTED", f"工作区文件不能是符号链接：{relative_path}", "将文件复制到工作区后重新导出。")
        source_files.append((relative_path, source))

    archive = Path(archive_path).expanduser().resolve()
    if archive.suffix.lower() not in {".zip", ".studyflow"}:
        archive = archive.with_suffix(".studyflow.zip")
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary_db_fd, temporary_db_name = tempfile.mkstemp(prefix=".studyflow-export-", suffix=".db", dir=archive.parent)
    temporary_archive_fd, temporary_archive_name = tempfile.mkstemp(prefix=".studyflow-export-", suffix=".tmp", dir=archive.parent)
    os.close(temporary_db_fd)
    os.close(temporary_archive_fd)
    temporary_db = Path(temporary_db_name)
    temporary_archive = Path(temporary_archive_name)
    try:
        _snapshot_sqlite(database_path, temporary_db)
        database_hash = _sha256_file(temporary_db)
        files = [
            {
                "relative_path": relative_path,
                "archive_path": f"files/{relative_path}",
                "size": source.stat().st_size,
                "sha256": _sha256_file(source),
            }
            for relative_path, source in source_files
        ]
        manifest = {
            "format": "studyflow-workspace",
            "format_version": WORKSPACE_FORMAT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_revision": revision,
            "workspace_name": settings.workspace_root.name,
            "database": {
                "archive_path": DATABASE_ARCHIVE_PATH,
                "size": temporary_db.stat().st_size,
                "sha256": database_hash,
            },
            "files": files,
        }
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive_file:
            archive_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            archive_file.write(temporary_db, DATABASE_ARCHIVE_PATH)
            for relative_path, source in source_files:
                archive_file.write(source, f"files/{relative_path}")
        os.replace(temporary_archive, archive)
        return {
            "archive_path": str(archive),
            "format_version": WORKSPACE_FORMAT_VERSION,
            "schema_revision": revision,
            "file_count": len(files),
            "database_size": manifest["database"]["size"],
            "manifest": manifest,
        }
    finally:
        temporary_db.unlink(missing_ok=True)
        temporary_archive.unlink(missing_ok=True)


def _read_manifest(archive_file: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(archive_file.read("manifest.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("BACKUP_MANIFEST_INVALID", "备份缺少可解析的 manifest.json。", "使用 StudyFlow 导出的完整备份文件。") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "studyflow-workspace" or manifest.get("format_version") != WORKSPACE_FORMAT_VERSION:
        raise DomainError("BACKUP_FORMAT_UNSUPPORTED", "备份格式或版本不受当前 StudyFlow 支持。", "使用同版本 StudyFlow 重新导出工作区。")
    revision = manifest.get("schema_revision")
    if revision not in SUPPORTED_SCHEMA_REVISIONS:
        raise DomainError("UNKNOWN_SCHEMA", f"备份声明了不支持的 schema 版本：{revision}", "先使用兼容版本迁移数据库，再导入当前 StudyFlow。")
    database = manifest.get("database")
    if not isinstance(database, dict) or database.get("archive_path") != DATABASE_ARCHIVE_PATH:
        raise DomainError("BACKUP_MANIFEST_INVALID", "备份数据库条目不完整。", "重新生成包含 database/studyflow.db 的备份。")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise DomainError("BACKUP_MANIFEST_INVALID", "备份 files 必须是列表。", "重新生成工作区备份。")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise DomainError("BACKUP_MANIFEST_INVALID", "备份 files 存在无效条目。", "重新生成工作区备份。")
        relative_path = _safe_relative(item.get("relative_path"), field="file.relative_path")
        if relative_path in seen or item.get("archive_path") != f"files/{relative_path}":
            raise DomainError("BACKUP_MANIFEST_INVALID", f"备份文件条目重复或映射错误：{relative_path}", "重新生成工作区备份。")
        if not isinstance(item.get("sha256"), str) or not isinstance(item.get("size"), int):
            raise DomainError("BACKUP_MANIFEST_INVALID", f"备份文件条目缺少大小或哈希：{relative_path}", "重新生成工作区备份。")
        seen.add(relative_path)
    return manifest


def _extract_member(archive_file: zipfile.ZipFile, member: str, destination: Path) -> None:
    normalized = _safe_archive_member(member)
    if normalized != member:
        raise DomainError("BACKUP_PATH_INVALID", f"备份条目路径未规范化：{member}", "重新生成不含路径穿越的备份。")
    info = archive_file.getinfo(member)
    if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise DomainError("BACKUP_SYMLINK_UNSUPPORTED", f"备份不能包含目录链接：{member}", "重新生成普通文件备份。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive_file.open(info, "r") as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)


def restore_workspace(archive_path: str | Path, target_root: str | Path) -> dict[str, Any]:
    """Restore into staging, validate, then atomically switch the workspace root."""
    archive = Path(archive_path).expanduser().resolve()
    if not archive.is_file():
        raise DomainError("BACKUP_NOT_FOUND", f"备份文件不存在：{archive}", "确认导出文件路径后重试。")
    target = Path(target_root).expanduser().resolve()
    if target.exists() and target.is_symlink():
        raise DomainError("BACKUP_PATH_INVALID", "恢复目标不能是符号链接目录。", "选择真实的本地目录作为恢复目标。")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent))
    previous: Path | None = None
    try:
        with zipfile.ZipFile(archive, "r") as archive_file:
            manifest = _read_manifest(archive_file)
            allowed = {"manifest.json", DATABASE_ARCHIVE_PATH}
            allowed.update(item["archive_path"] for item in manifest["files"])
            for info in archive_file.infolist():
                if info.is_dir():
                    continue
                member = _safe_archive_member(info.filename)
                if member not in allowed:
                    raise DomainError("BACKUP_ARCHIVE_UNEXPECTED_FILE", f"备份包含未声明文件：{member}", "重新生成只包含 manifest、数据库和声明文件的备份。")
            if DATABASE_ARCHIVE_PATH not in archive_file.namelist():
                raise DomainError("BACKUP_DATABASE_MISSING", "备份缺少 SQLite 数据库。", "重新生成完整工作区备份。")
            staged_database = staging / ".studyflow" / "studyflow.db"
            _extract_member(archive_file, DATABASE_ARCHIVE_PATH, staged_database)
            database_meta = manifest["database"]
            if staged_database.stat().st_size != database_meta.get("size") or _sha256_file(staged_database) != database_meta.get("sha256"):
                raise DomainError("BACKUP_HASH_MISMATCH", "备份数据库大小或哈希校验失败。", "不要覆盖原工作区，重新导出备份。")
            for item in manifest["files"]:
                member = item["archive_path"]
                if member not in archive_file.namelist():
                    raise DomainError("BACKUP_FILE_MISSING", f"备份缺少声明文件：{item['relative_path']}", "重新生成包含全部 Markdown 文件的备份。")
                destination = _workspace_file(staging, item["relative_path"])
                _extract_member(archive_file, member, destination)
                if destination.stat().st_size != item["size"] or _sha256_file(destination) != item["sha256"]:
                    raise DomainError("BACKUP_HASH_MISMATCH", f"文件校验失败：{item['relative_path']}", "不要覆盖原工作区，重新导出备份。")
        actual_revision, _ = _schema_revision(staged_database)
        if actual_revision != manifest["schema_revision"]:
            raise DomainError("BACKUP_SCHEMA_MISMATCH", f"数据库实际 schema 与 manifest 不一致：{actual_revision} != {manifest['schema_revision']}", "重新导出同一工作区的备份。")

        if target.exists():
            previous = target.with_name(f".{target.name}.before-restore-{uuid4().hex}")
            target.rename(previous)
        staging.rename(target)
        return {
            "workspace_root": str(target),
            "schema_revision": manifest["schema_revision"],
            "file_count": len(manifest["files"]),
            "replaced_existing": previous is not None,
            "previous_workspace": str(previous) if previous else None,
            "manifest": manifest,
        }
    except Exception:
        # The original target is never removed. A failed staging directory is
        # intentionally retained for diagnosis and possible manual cleanup.
        if previous is not None and previous.exists() and not target.exists():
            previous.rename(target)
        raise

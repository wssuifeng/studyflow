"""Open an existing data store for inspection without initialization or migration."""
import sqlite3

from sqlalchemy import create_engine, inspect, text

from studyflow.shared.domain import DomainError
from .database import build_engine


def open_read_engine(settings, *, validate_schema=True):
    if settings.database_url.startswith("sqlite"):
        path = settings.database_path
        if path is None or not path.is_file():
            raise DomainError("WORKSPACE_NOT_INITIALIZED", "所选工作区没有已有数据库；只读查询未创建任何内容。", "确认数据工作区路径；新工作区请显式初始化。")
        # mode=ro also closes the exists()/connect race: never create a missing file.
        uri = path.resolve().as_uri() + "?mode=ro"

        def connect():
            connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA temp_store=MEMORY")
            return connection

        engine = create_engine(settings.database_url, creator=connect, future=True)
    else:
        engine = build_engine(settings)
    try:
        if validate_schema:
            from . import registry  # noqa: F401
            from .base import Base
            from .migrations import CURRENT_REVISION

            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            if "alembic_version" in tables:
                with engine.connect() as connection:
                    revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
                if revision and str(revision).split("_")[0].isdigit() and int(str(revision).split("_")[0]) > int(CURRENT_REVISION.split("_")[0]):
                    raise DomainError("NEWER_SCHEMA_UNSUPPORTED", "工作区由更新版本创建；只读查询未修改数据库。", "使用匹配的新版本CLI/应用。")
                if revision and revision != CURRENT_REVISION:
                    raise DomainError("SCHEMA_UPGRADE_REQUIRED", "工作区需要受控升级；只读查询未修改数据库。", "确认工作区后显式执行升级，或使用匹配版本。")
            missing = [name for name, table in Base.metadata.tables.items()
                       if name not in tables or not set(table.columns.keys()).issubset({c["name"] for c in inspector.get_columns(name)})]
            if missing:
                raise DomainError("SCHEMA_UPGRADE_REQUIRED", "已有数据库结构不兼容；只读查询未创建表或迁移。", "使用匹配版本，或在确认工作区后显式执行受控升级。")
        return engine
    except Exception:
        engine.dispose()
        raise

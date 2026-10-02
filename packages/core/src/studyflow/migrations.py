"""Compatibility import; implementation lives in studyflow.infrastructure.persistence.migrations."""
from studyflow.infrastructure.persistence.migrations import _alembic_config, _alembic_upgrade, _alembic_stamp, _sqlite_path, _columns, backup_sqlite, upgrade_sqlite, LEGACY_TABLES, CONSOLE_TABLES, CURRENT_REVISION, GENERAL_COLUMNS

__all__ = ['_alembic_config', '_alembic_upgrade', '_alembic_stamp', '_sqlite_path', '_columns', 'backup_sqlite', 'upgrade_sqlite', 'LEGACY_TABLES', 'CONSOLE_TABLES', 'CURRENT_REVISION', 'GENERAL_COLUMNS']

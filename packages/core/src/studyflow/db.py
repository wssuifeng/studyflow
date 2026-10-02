"""Compatibility import; implementation lives in studyflow.infrastructure.persistence.database."""
from studyflow.infrastructure.persistence.database import Base, build_engine, build_session_factory, init_db, ensure_compatible_schema, get_session

__all__ = ['Base', 'build_engine', 'build_session_factory', 'init_db', 'ensure_compatible_schema', 'get_session']

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from studyflow.config import Settings
from studyflow.db import init_db
from studyflow.services import AppService


@pytest.fixture
def app_service(tmp_path):
    settings = Settings(workspace_root=tmp_path, database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    init_db(engine)
    return AppService(settings, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))

from __future__ import annotations

from .config import Settings
from .infrastructure.resources import ensure_demo_content
from .db import build_engine, build_session_factory, init_db
from .services import AppService


def seed(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    settings.ensure_layout()
    ensure_demo_content(settings.workspace_root)
    engine = build_engine(settings)
    init_db(engine)
    return AppService(settings, build_session_factory(engine)).seed_demo()

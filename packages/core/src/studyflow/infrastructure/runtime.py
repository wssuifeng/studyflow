from contextlib import contextmanager
from typing import Iterator
from sqlalchemy.orm import Session, sessionmaker
from studyflow.infrastructure.config import Settings
from studyflow.infrastructure.persistence.base import EventLog
from studyflow.shared.ids import new_id

class Runtime:
    """Shared database runtime; a nested module operation receives the caller's Session."""
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]):
        self.settings = settings
        self.session_factory = session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def event(self, session: Session, source: str, object_type: str, object_id: str, action: str, summary: str) -> None:
        session.add(EventLog(id=new_id(), source=source, object_type=object_type, object_id=object_id, action=action, summary=summary))

class Service:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    @property
    def settings(self):
        return self.runtime.settings

    @property
    def session_factory(self):
        return self.runtime.session_factory

    def session(self):
        return self.runtime.session()

    def _event(self, *args, **kwargs):
        return self.runtime.event(*args, **kwargs)

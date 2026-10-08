from contextlib import contextmanager
from typing import Iterator
from sqlalchemy.orm import Session, sessionmaker
from studyflow.infrastructure.config import Settings
from studyflow.infrastructure.persistence.base import EventLog
from studyflow.shared.ids import new_id

class Runtime:
    """Shared database runtime; a nested module operation receives the caller's Session."""
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session], read_only: bool = False):
        self.settings = settings
        self.session_factory = session_factory
        self.read_only = read_only

    @contextmanager
    def session(self, read_only: bool | None = None) -> Iterator[Session]:
        """Open a session without turning a read-only query into a workspace write.

        ``read_only=True`` deliberately skips the cross-process lease and never
        commits. Callers use it for inventory/diagnostic paths that must work
        when the workspace parent is not writable.
        """
        effective_read_only = self.read_only if read_only is None else read_only
        lease = None
        if not effective_read_only:
            from studyflow.infrastructure.leases import workspace_lease
            lease = workspace_lease(self.settings.workspace_root)
            lease.__enter__()
        session = self.session_factory()
        try:
            yield session
            if effective_read_only:
                session.rollback()
            else:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            if lease is not None:
                lease.__exit__(None, None, None)

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

    def session(self, read_only: bool | None = None):
        return self.runtime.session(read_only=read_only)

    def _event(self, *args, **kwargs):
        return self.runtime.event(*args, **kwargs)

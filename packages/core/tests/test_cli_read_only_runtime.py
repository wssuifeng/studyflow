from pathlib import Path

from studyflow.infrastructure.config import Settings
from studyflow.infrastructure.runtime import Runtime


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_read_only_session_skips_workspace_lease_and_never_commits(monkeypatch, tmp_path: Path):
    def lease_must_not_be_called(*args, **kwargs):
        raise AssertionError("read-only inspection must not create a workspace lease")

    import studyflow.infrastructure.leases as leases

    monkeypatch.setattr(leases, "workspace_lease", lease_must_not_be_called)
    fake = FakeSession()
    runtime = Runtime(
        Settings(workspace_root=tmp_path, database_url="sqlite:///:memory:"),
        lambda: fake,
        read_only=True,
    )

    with runtime.session():
        pass

    assert fake.commits == 0
    assert fake.rollbacks == 1
    assert fake.closed == 1


def test_write_session_still_requires_lease(monkeypatch, tmp_path: Path):
    entered = []

    class Lease:
        def __enter__(self):
            entered.append("enter")
            return self

        def __exit__(self, *args):
            entered.append("exit")

    import studyflow.infrastructure.leases as leases

    monkeypatch.setattr(leases, "workspace_lease", lambda *args, **kwargs: Lease())
    fake = FakeSession()
    runtime = Runtime(
        Settings(workspace_root=tmp_path, database_url="sqlite:///:memory:"),
        lambda: fake,
    )

    with runtime.session():
        pass

    assert entered == ["enter", "exit"]
    assert fake.commits == 1
    assert fake.rollbacks == 0
    assert fake.closed == 1

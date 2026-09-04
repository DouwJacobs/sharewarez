from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sharewarez.job_worker import maintain_downloads
from sharewarez.models import DownloadTransfer, User


class OneTick:
    stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, interval):
        assert interval == 15
        self.stopped = True


def test_worker_retires_stale_transfer_without_page_visit(app, db_session):
    suffix = uuid4().hex
    user = User(name=f"maintenance-{suffix}", email=f"{suffix}@example.test", role="user", password_hash="test")
    db_session.add(user)
    db_session.flush()
    now = datetime.now(timezone.utc)
    stale = DownloadTransfer(user_id=user.id, filename="stale", bytes_sent=10, reserved_bytes=100,
                             last_activity_at=now-timedelta(seconds=90))
    active = DownloadTransfer(user_id=user.id, filename="active", last_activity_at=now)
    db_session.add_all([stale, active])
    db_session.commit()
    stale_id, active_id = stale.id, active.id
    maintain_downloads(app, OneTick())
    db_session.expire_all()
    assert db_session.get(DownloadTransfer, stale_id).status == "interrupted"
    assert db_session.get(DownloadTransfer, stale_id).reserved_bytes == 10
    assert db_session.get(DownloadTransfer, active_id).status == "active"


def test_maintenance_survives_failed_tick(app, monkeypatch):
    calls = []
    def fail():
        calls.append(1)
        raise RuntimeError("simulated database interruption")
    monkeypatch.setattr("sharewarez.utils.download_limits.mark_stale_transfers", fail)
    stop = OneTick()
    maintain_downloads(app, stop)
    assert calls == [1] and stop.stopped

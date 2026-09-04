"""Disposable local UI fixture; never run against a populated or production DB.

Run from the repository with TEST_DATABASE_URL pointing at a fresh test database:
python -m tests.preview_download_live
Open http://localhost:5007/_preview/session to enter the fixture's admin session.
"""
import os
import threading
import time

from sqlalchemy.engine import make_url

url = os.environ["TEST_DATABASE_URL"]
if "test" not in (make_url(url).database or "").lower():
    raise RuntimeError("Preview requires an explicitly named test database")
os.environ["DATABASE_URL"] = url
os.environ["PYTEST_CURRENT_TEST"] = "isolated-live-preview"

from flask import redirect, session
from alembic import command
from sharewarez import create_app, db
from sharewarez.models import User, DownloadTransfer, DownloadArchive, DownloadRequest, Game, Library, BackgroundJob
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.migrations import alembic_config
from asgi import LazyASGIApp
import uvicorn

app = create_app()
app.config.update(SECRET_KEY="disposable-live-preview-only", TESTING=True)
with app.app_context():
    db.create_all()
    if db.session.query(User).count():
        raise RuntimeError("Preview requires an empty disposable database")
    user = User(name="Preview administrator", email="preview@example.test", role="admin", state=True,
                is_email_verified=True, password_hash="not-a-login-password")
    db.session.add(user)
    db.session.flush()
    user_id = user.id
    transfer = DownloadTransfer(user_id=user_id, filename="Large game archive.zip", bytes_sent=104857600,
                                reserved_bytes=53687091200)
    db.session.add(transfer)
    db.session.commit()
    transfer_id = transfer.id
    library = Library(name="Preview library", platform=LibraryPlatform.PCWIN)
    db.session.add(library)
    db.session.flush()
    game = Game(name="Preview resumable game", library_uuid=library.uuid)
    archive = DownloadArchive(id="11111111-1111-4111-8111-111111111111", cache_key="1" * 64,
                              source_path="/preview-only", display_name="Preview game archive", state="building",
                              source_bytes=104857600, bytes_written=10485760)
    job = BackgroundJob(task_name="download.archive.build", queue="archive", status="running",
                        progress=10, progress_message="Writing archive")
    db.session.add(job)
    db.session.flush()
    archive.build_job_id = job.id
    db.session.add_all([game, archive])
    db.session.flush()
    download = DownloadRequest(user_id=user_id, game_uuid=game.uuid, archive_id=archive.id,
                               status="processing", delivery_kind="cached_archive", download_size=104857600)
    db.session.add(download)
    db.session.commit()
    archive_id, download_id = archive.id, download.id
    db.session.remove()
config = alembic_config(url)
command.stamp(config, "20260902_23", purge=True)
command.upgrade(config, "20260904_24")


@app.route("/_preview/session")
def preview_session():
    session["_user_id"] = str(user_id)
    session["_fresh"] = True
    return redirect("/admin/manage-downloads")


def simulate():
    from datetime import datetime, timezone
    tick = 0
    while True:
        time.sleep(1)
        with app.app_context():
            item = db.session.get(DownloadTransfer, transfer_id)
            item.bytes_sent += 8388608
            item.last_activity_at = datetime.now(timezone.utc)
            tick += 1
            archive = db.session.get(DownloadArchive, archive_id)
            request = db.session.get(DownloadRequest, download_id)
            job = archive.build_job
            phase = tick % 45
            archive.state = "building" if phase < 30 else "ready"
            archive.bytes_written = min(104857600, phase * 3495253)
            archive.archive_bytes = 104857600 if phase >= 30 else 0
            request.status = "processing" if phase < 30 else "available"
            job.progress = min(100, round(phase / 30 * 100))
            job.progress_message = "Publishing archive" if 27 <= phase < 30 else "Writing archive"
            job.status = "running" if phase < 30 else "completed"
            db.session.commit()


if __name__ == "__main__":
    threading.Thread(target=simulate, daemon=True).start()
    application = LazyASGIApp()
    application._flask_app = app
    uvicorn.run(application, host="0.0.0.0", port=5007, access_log=False)

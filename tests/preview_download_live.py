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
from sharewarez.models import User, DownloadTransfer
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
    while True:
        time.sleep(1)
        with app.app_context():
            item = db.session.get(DownloadTransfer, transfer_id)
            item.bytes_sent += 8388608
            item.last_activity_at = datetime.now(timezone.utc)
            db.session.commit()


if __name__ == "__main__":
    threading.Thread(target=simulate, daemon=True).start()
    application = LazyASGIApp()
    application._flask_app = app
    uvicorn.run(application, host="0.0.0.0", port=5007, access_log=False)

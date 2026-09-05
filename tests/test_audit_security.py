"""Audit regressions across actual requests and committed database state."""

import asyncio
from uuid import uuid4
from unittest.mock import patch
import pytest
from sharewarez.models import User, Library, Game
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.auth import load_user
from asgi import LazyASGIApp


@pytest.fixture
def audit_member(db_session):
    suffix = uuid4().hex
    user = User(name=suffix, email=f"{suffix}@example.com", role="user", state=True, password_hash="unused")
    db_session.add(user)
    db_session.commit()
    return user


def signin(client, user):
    with client.session_transaction() as s:
        s["_user_id"] = str(user.id)
        s["_fresh"] = True


def test_member_cannot_move_catalogue(client, db_session, audit_member):
    first = Library(name="First", platform=LibraryPlatform.PCWIN)
    second = Library(name="Second", platform=LibraryPlatform.PCWIN)
    db_session.add_all([first, second])
    db_session.flush()
    game = Game(name="Protected catalogue", library_uuid=first.uuid)
    db_session.add(game)
    db_session.commit()
    signin(client, audit_member)
    r = client.post("/api/move_game_to_library", json={"game_uuid": game.uuid, "target_library_uuid": second.uuid})
    assert r.status_code in (302, 403)
    db_session.refresh(game)
    assert game.library_uuid == first.uuid


def test_disabled_session_rejected_for_reads_and_mutations(client, db_session, audit_member):
    signin(client, audit_member)
    assert client.get("/api/current_user_role").status_code == 200
    audit_member.state = False
    db_session.commit()
    assert client.get("/api/current_user_role").status_code == 302
    assert client.post("/api/preferences/library", json={"action": "set_view", "view": "list"}).status_code == 302
    assert load_user(audit_member.id) is None


@pytest.mark.parametrize("value", ["invalid", None, "-10"])
def test_invalid_session_identifiers_are_anonymous(app, value):
    with app.app_context():
        assert load_user(value) is None


def test_direct_download_rechecks_disabled_account(app, client, db_session, audit_member):
    signin(client, audit_member)
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"]).value
    scope = {"scheme": "http", "headers": [(b"cookie", f"session={cookie}".encode())]}
    application = LazyASGIApp()
    application._flask_app = app
    assert asyncio.run(application._get_user_from_session(scope)) == audit_member.id
    audit_member.state = False
    db_session.commit()
    assert asyncio.run(application._get_user_from_session(scope)) is None


def test_invalid_setup_never_logs_password(client, capsys):
    marker = "audit-password-must-not-be-logged"
    with patch("sharewarez.routes_setup.is_setup_required", return_value=True):
        r = client.post(
            "/setup/submit",
            data={"username": "audit", "email": "invalid", "password": marker, "confirm_password": "mismatch"},
        )
    assert r.status_code == 200
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err


def test_access_logs_redact_tokens_even_on_unmatched_routes(client, capsys):
    marker = "audit-secret-token-should-not-be-logged"
    client.get("/reset_password/" + marker)
    client.get("/unknown/" + marker)
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err


def test_launcher_stops_on_initialization_failure(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    launcher = tmp_path / "startweb.sh"
    shutil.copy2(root / "startweb.sh", launcher)
    commands = tmp_path / "bin"
    commands.mkdir()
    (commands / "python3").write_text("#!/bin/sh\nexit 17\n")
    (commands / "uvicorn").write_text('#!/bin/sh\ntouch "$AUDIT_LAUNCH_MARKER"\n')
    for command in commands.iterdir():
        command.chmod(0o755)
    marker = tmp_path / "launched"
    env = {
        **os.environ,
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "VIRTUAL_ENV": str(tmp_path),
        "AUDIT_LAUNCH_MARKER": str(marker),
    }
    result = subprocess.run(["bash", str(launcher), "--no-reload"], env=env, capture_output=True, text=True)
    assert result.returncode == 17
    assert not marker.exists()


def test_launchers_use_redacted_application_access_logs():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name in ['startweb.sh', 'startweb-docker.sh', 'startweb_windows.cmd']:
        launches = [line for line in (root / name).read_text().splitlines()
                    if line.strip().startswith('uvicorn ')]
        assert launches
        assert all('--no-access-log' in line for line in launches)
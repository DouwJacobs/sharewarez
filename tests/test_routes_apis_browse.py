"""Real filesystem and role regressions for the administrator browser."""

import os
from uuid import uuid4
from unittest.mock import patch
import pytest
from sharewarez.models import User


@pytest.fixture
def browser_user(db_session):
    suffix = uuid4().hex
    user = User(name=suffix, email=f"{suffix}@example.com", role="admin", password_hash="unused")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def browser_client(app, client, browser_user, tmp_path):
    base = tmp_path / "allowed"
    base.mkdir()
    app.config["BASE_FOLDER_POSIX"] = str(base)
    app.config["BASE_FOLDER_WINDOWS"] = str(base)
    with client.session_transaction() as s:
        s["_user_id"] = str(browser_user.id)
        s["_fresh"] = True
    return client, base


def test_browse_requires_login(client):
    assert client.get("/api/browse_folders_ss").status_code == 302


def test_browse_requires_admin(browser_client, browser_user, db_session):
    client, _ = browser_client
    browser_user.role = "user"
    db_session.commit()
    assert client.get("/api/browse_folders_ss").status_code == 302


def test_browse_metadata_and_sorting(browser_client):
    client, base = browser_client
    (base / "zfolder").mkdir()
    (base / "afolder").mkdir()
    (base / "B.TXT").write_bytes(b"12345")
    (base / "a").write_bytes(b"x")
    r = client.get("/api/browse_folders_ss")
    assert r.status_code == 200
    assert r.json["items"] == [
        {"name": "afolder", "isDir": True, "ext": None, "size": None},
        {"name": "zfolder", "isDir": True, "ext": None, "size": None},
        {"name": "a", "isDir": False, "ext": "", "size": 1},
        {"name": "B.TXT", "isDir": False, "ext": "txt", "size": 5},
    ]
    assert r.json["basePath"] == str(base)


@pytest.mark.parametrize("kind", ["parent", "sibling", "absolute", "symlink"])
def test_boundary_escape_denied(browser_client, kind):
    client, base = browser_client
    sibling = base.parent / "allowed-sibling"
    sibling.mkdir()
    (sibling / "private.txt").write_text("synthetic")
    paths = {"parent": "..", "sibling": "../allowed-sibling", "absolute": str(sibling), "symlink": "escape"}
    if kind == "symlink":
        try:
            (base / "escape").symlink_to(sibling, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks unavailable")
    assert client.get("/api/browse_folders_ss", query_string={"path": paths[kind]}).status_code == 403


def test_subdirectory_and_internal_symlink(browser_client):
    client, base = browser_client
    (base / "nested").mkdir()
    assert client.get("/api/browse_folders_ss?path=nested").json["items"] == []
    if os.name != "nt":
        (base / "alias").symlink_to(base / "nested", target_is_directory=True)
        assert client.get("/api/browse_folders_ss?path=alias").status_code == 200


def test_missing_directory(browser_client):
    client, _ = browser_client
    assert client.get("/api/browse_folders_ss?path=missing").status_code == 404


def test_unreadable_directory(browser_client):
    client, _ = browser_client
    with patch("sharewarez.routes_apis.browse.os.listdir", side_effect=PermissionError):
        assert client.get("/api/browse_folders_ss").status_code == 403


def test_broken_and_external_children_do_not_hide_readable_items(browser_client):
    client, base = browser_client
    (base / "Game").mkdir()
    outside = base.parent / "private.iso"
    outside.write_bytes(b"private")
    (base / "broken").symlink_to(base / "missing")
    (base / "escape").symlink_to(outside)
    response = client.get("/api/browse_folders_ss")
    assert response.status_code == 200
    assert response.json["items"] == [
        {"name": "Game", "isDir": True, "ext": None, "size": None}
    ]
    assert response.json["skippedItems"] == 2
    assert response.json["hasErrors"] is True
    assert "private" not in response.get_data(as_text=True)


def test_inaccessible_child_is_skipped(browser_client):
    client, base = browser_client
    (base / "good.iso").write_bytes(b"ok")
    (base / "bad.iso").write_bytes(b"bad")
    original = os.stat

    def inspect(path, *args, **kwargs):
        if os.fspath(path) == str(base / "bad.iso"):
            raise PermissionError("fixture")
        return original(path, *args, **kwargs)

    with patch("sharewarez.routes_apis.browse.os.stat", side_effect=inspect):
        response = client.get("/api/browse_folders_ss")
    assert response.status_code == 200
    assert [item["name"] for item in response.json["items"]] == ["good.iso"]
    assert response.json["skippedItems"] == 1


def test_empty_root_has_explicit_success_contract(browser_client):
    client, _ = browser_client
    response = client.get("/api/browse_folders_ss")
    assert response.json["items"] == []
    assert response.json["currentPath"] == ""
    assert response.json["skippedItems"] == 0
    assert response.json["hasErrors"] is False

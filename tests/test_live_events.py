import asyncio
import threading
import importlib.util
import os
from pathlib import Path
import select
import uuid

import pytest
import psycopg2
from psycopg2 import sql
from alembic import command
from sqlalchemy import text

from sharewarez.live_events import CHANNEL, ConnectionLimitError, LiveEventHub, PostgresEventListener
from sharewarez import db
from sharewarez.utils.migrations import alembic_config


def test_initial_snapshot_topics_and_unsubscribe():
    async def run():
        hub = LiveEventHub()
        transfers = hub.subscribe(1, {"transfers"})
        archives = hub.subscribe(2, {"archives"})
        assert transfers.changed.is_set() and archives.changed.is_set()
        transfers.changed.clear()
        archives.changed.clear()
        hub.signal({"transfers"})
        await asyncio.sleep(0)
        assert transfers.changed.is_set()
        assert not archives.changed.is_set()
        hub.unsubscribe(transfers)
        hub.unsubscribe(transfers)
        assert 1 not in hub._users
        assert hub.subscribe(1, {"transfers"}).changed.is_set()
    asyncio.run(run())


def test_postgres_trigger_commit_rollback_and_multiple_listeners(monkeypatch):
    """Exercise the actual migration SQL without touching the application's tables."""
    dsn = os.environ["TEST_DATABASE_URL"]
    schema = "live_test_" + uuid.uuid4().hex
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    listeners = [psycopg2.connect(dsn) for _ in range(2)]
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            for table in ("download_transfers", "download_requests", "download_archives", "background_jobs"):
                cursor.execute(sql.SQL("CREATE TABLE {} (id int, task_name text)").format(sql.Identifier(table)))
            path = Path(__file__).parents[1] / "migrations/versions/20260904_24_download_live_events.py"
            spec = importlib.util.spec_from_file_location("live_migration", path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            monkeypatch.setattr(migration.op, "execute", cursor.execute)
            migration.upgrade()
            for listener in listeners:
                listener.autocommit = True
                with listener.cursor() as listen_cursor:
                    listen_cursor.execute(f"LISTEN {CHANNEL}")
            connection.autocommit = False
            cursor.execute("INSERT INTO download_transfers VALUES (1, NULL), (2, NULL)")
            assert not select.select(listeners, [], [], 0.05)[0]
            connection.commit()
            for listener in listeners:
                assert select.select([listener], [], [], 2)[0]
                listener.poll()
                assert [n.payload for n in listener.notifies] == ["transfers"]
                listener.notifies.clear()
            cursor.execute("UPDATE download_transfers SET id=3")
            connection.rollback()
            cursor.execute("UPDATE download_transfers SET id=id")
            cursor.execute("INSERT INTO background_jobs VALUES (1, 'scan.library')")
            connection.commit()
            assert not select.select(listeners, [], [], 0.05)[0]
            cursor.execute("INSERT INTO background_jobs VALUES (2, 'download.archive.build')")
            connection.commit()
            for listener in listeners:
                assert select.select([listener], [], [], 2)[0]
                listener.poll()
                assert [n.payload for n in listener.notifies] == ["archives"]
            migration.downgrade()
            connection.commit()
    finally:
        connection.rollback()
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        connection.close()
        for listener in listeners:
            listener.close()


def test_listener_reconnect_resynchronizes_and_stops():
    async def run():
        dsn = os.environ["TEST_DATABASE_URL"]
        hub = LiveEventHub()
        subscription = hub.subscribe(1, {"transfers"})
        listener = PostgresEventListener(dsn, hub, retry_seconds=0.05)
        listener.start()
        sender = psycopg2.connect(dsn)
        sender.autocommit = True
        try:
            assert await asyncio.to_thread(listener.ready.wait, 3)
            await asyncio.sleep(0.05)
            subscription.changed.clear()
            with sender.cursor() as cursor:
                cursor.execute("SELECT pg_notify(%s, %s)", (CHANNEL, "transfers"))
            await asyncio.wait_for(subscription.changed.wait(), 3)
            subscription.changed.clear()
            # Terminate this test's sole dedicated listener to simulate a restart.
            with sender.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                               "WHERE application_name='sharewarez-live' AND datname=current_database()")
            await asyncio.wait_for(subscription.changed.wait(), 3)
        finally:
            sender.close()
            await asyncio.to_thread(listener.stop)
        assert not listener._thread.is_alive()
        assert not listener.ready.is_set()
    asyncio.run(run())


def test_live_migration_against_application_schema(app):
    config = alembic_config(app.config["SQLALCHEMY_DATABASE_URI"])
    command.stamp(config, "20260902_23", purge=True)
    command.upgrade(config, "20260904_24")
    with app.app_context():
        count = db.session.execute(text("SELECT count(*) FROM pg_trigger WHERE "
                                        "tgname='live_download_change' AND NOT tgisinternal")).scalar_one()
        assert count == 4
        db.session.remove()
    command.downgrade(config, "20260902_23")
    command.upgrade(config, "20260904_24")


def test_connection_limits_release_and_validate_topics():
    async def run():
        hub = LiveEventHub(max_connections=2, per_user=1)
        first = hub.subscribe(1, {"transfers"})
        with pytest.raises(ConnectionLimitError):
            hub.subscribe(1, {"archives"})
        hub.subscribe(2, {"archives"})
        with pytest.raises(ConnectionLimitError):
            hub.subscribe(3, {"archives"})
        hub.unsubscribe(first)
        hub.subscribe(3, {"archives"})
        with pytest.raises(ValueError):
            hub.subscribe(4, {"secrets"})
    asyncio.run(run())


def test_slow_consumer_and_thread_burst_are_bounded():
    async def run():
        hub = LiveEventHub()
        subscription = hub.subscribe(1, {"transfers"})
        subscription.changed.clear()
        def burst():
            for _ in range(10000):
                hub.signal({"transfers", "unrecognized"})
        thread = threading.Thread(target=burst)
        thread.start()
        thread.join()
        assert hub._pending == {"transfers"}
        assert hub._scheduled
        await asyncio.sleep(0)
        assert subscription.changed.is_set()
        assert not hub._pending and not hub._scheduled
        # A slow consumer keeps one dirty bit, not 10,000 queued messages.
        hub.signal({"transfers"})
        await asyncio.sleep(0)
        assert subscription.changed.is_set()
    asyncio.run(run())

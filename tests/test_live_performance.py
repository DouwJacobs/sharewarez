"""Representative local measurements; timings are reported, not flaky pass gates."""
import json
import time
import tracemalloc
from uuid import uuid4

from sqlalchemy import event, select

from sharewarez import db
from sharewarez.live_snapshot_cache import SnapshotCache
from sharewarez.live_snapshots import snapshot
from sharewarez.models import User, DownloadTransfer, DownloadArchive
from sharewarez.utils.download_cache import archive_summary


def test_representative_snapshot_costs(app, db_session, tmp_path):
    app.config['DOWNLOAD_CACHE_DIR'] = str(tmp_path / 'cache')
    suffix = uuid4().hex
    viewers = [User(name=f'perf-{i}-{suffix}', email=f'{i}-{suffix}@example.test', role='admin',
                    state=True, password_hash='test') for i in range(10)]
    db_session.add_all(viewers); db_session.flush()
    db_session.add_all([DownloadTransfer(user_id=viewers[i % 10].id,filename=f'file-{i}',reserved_bytes=100000000,
                                        bytes_sent=1000000) for i in range(100)])
    db_session.add_all([DownloadArchive(id=str(uuid4()),cache_key=uuid4().hex * 2,source_path='/benchmark-only',
                                        display_name=f'archive-{i}',state='ready',archive_bytes=1000000)
                       for i in range(2000)])
    db_session.commit()
    scopes = [{'headers':[(b'cookie',('session=' + app.session_interface.get_signing_serializer(app).dumps(
        {'_user_id':str(user.id)})).encode())]} for user in viewers]
    db_session.remove()
    queries = []
    def count(*args):
        queries.append(1)
    event.listen(db.engine,'before_cursor_execute',count)
    try:
        def measure(fn):
            queries.clear()
            tracemalloc.start()
            start = time.perf_counter()
            result = fn()
            elapsed = (time.perf_counter() - start) * 1000
            _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
            return result, {'queries':len(queries),'elapsed_ms':round(elapsed,2),'peak_kib':round(peak/1024,1)}
        _, baseline = measure(lambda:[snapshot(app,scope,'activity',()) for scope in scopes])
        # One sample round: a long TTL avoids machine-speed-dependent cache misses.
        cache = SnapshotCache(ttl=60)
        _, shared = measure(lambda:[snapshot(app,scope,'activity',(),cache=cache) for scope in scopes])
        assert shared['queries'] == 11  # Ten independent authorizations, one transfer query.
        assert baseline['queries'] == 20
        def old_inventory():
            archives = db.session.execute(select(DownloadArchive)).scalars().all()
            return sum(item.archive_bytes for item in archives if item.state == 'ready')
        old_total, old = measure(old_inventory)
        db.session.remove()
        new_summary, new = measure(archive_summary)
        assert old_total == new_summary['used_bytes']
        print('\nLIVE_PERFORMANCE=' + json.dumps({'viewers':10,'transfers':100,'archives':2000,
              'unshared_snapshots':baseline,'shared_snapshots':shared,'old_inventory':old,'aggregated_inventory':new}))
    finally:
        event.remove(db.engine,'before_cursor_execute',count)

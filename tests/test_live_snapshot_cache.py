from concurrent.futures import ThreadPoolExecutor
import threading

from sharewarez.live_snapshot_cache import SnapshotCache


def test_cache_bounds_ttl_and_scope_keys():
    now = [0]
    cache = SnapshotCache(capacity=2, clock=lambda: now[0])
    calls = []
    def load():
        calls.append(1)
        return len(calls)
    assert cache.get(('downloads',1,()),load) == 1
    assert cache.get(('downloads',1,()),load) == 1
    assert cache.get(('downloads',2,()),load) == 2
    now[0] = 1
    assert cache.get(('downloads',1,()),load) == 3
    cache.get(('cache',None,()),load)
    assert len(cache._entries) == 2


def test_concurrent_readers_share_one_load():
    cache = SnapshotCache()
    gate = threading.Barrier(8)
    calls = []
    def reader():
        gate.wait()
        return cache.get('activity', lambda: calls.append(1) or {'value':42})
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: reader(), range(8)))
    assert calls == [1] and all(result == {'value':42} for result in results)

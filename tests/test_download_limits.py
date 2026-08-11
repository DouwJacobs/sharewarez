import asyncio

from sharewarez.utils.download_limits import throttle_chunks
from sharewarez.routes_admin_ext.settings import validate_settings_data


def test_unlimited_throttle_preserves_chunks():
    async def chunks():
        yield b"first"
        yield b"second"

    async def collect():
        return [chunk async for chunk in throttle_chunks(chunks(), 0)]

    assert asyncio.run(collect()) == [b"first", b"second"]


def test_positive_throttle_sleeps(monkeypatch):
    sleeps = []

    async def chunks():
        yield b"x" * 125_000

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("sharewarez.utils.download_limits.time.monotonic", lambda: 0)
    monkeypatch.setattr("sharewarez.utils.download_limits.asyncio.sleep", fake_sleep)

    async def collect():
        return [chunk async for chunk in throttle_chunks(chunks(), 1)]

    assert asyncio.run(collect()) == [b"x" * 125_000]
    assert sleeps == [1.0]


def test_download_delivery_settings_validation():
    assert validate_settings_data({
        "maxConcurrentDownloadsPerUser": 3,
        "downloadBandwidthLimitMbps": 25.5,
    }) == []
    errors = validate_settings_data({
        "maxConcurrentDownloadsPerUser": 0,
        "downloadBandwidthLimitMbps": -1,
    })
    assert "Concurrent downloads per user must be between 1 and 20" in errors
    assert "Download bandwidth limit must be between 0 and 10000 Mbps" in errors

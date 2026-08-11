import asyncio

from sharewarez.utils.download_limits import (
    estimate_path_bytes,
    normalize_download_priority,
    throttle_chunks,
)
from sharewarez.routes_admin_ext.settings import validate_settings_data
from sharewarez.routes_admin_ext.users import validate_monthly_download_quota


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
        "downloadQueueWaitSeconds": 15,
        "defaultMonthlyDownloadQuotaGb": 250,
    }) == []
    errors = validate_settings_data({
        "maxConcurrentDownloadsPerUser": 0,
        "downloadBandwidthLimitMbps": -1,
        "downloadQueueWaitSeconds": 61,
    })
    assert "Concurrent downloads per user must be between 1 and 20" in errors
    assert "Download bandwidth limit must be between 0 and 10000 Mbps" in errors
    assert "Download queue wait must be between 0 and 60 seconds" in errors


def test_download_priority_is_normalized():
    assert normalize_download_priority(-50) == -10
    assert normalize_download_priority('7') == 7
    assert normalize_download_priority(50) == 10
    assert normalize_download_priority(None) == 0


def test_estimate_path_bytes_counts_directory_files(tmp_path):
    (tmp_path / "one.bin").write_bytes(b"1234")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two.bin").write_bytes(b"567")
    assert estimate_path_bytes(tmp_path) == 7


def test_monthly_download_quota_validation():
    assert validate_monthly_download_quota(None) == (True, "")
    assert validate_monthly_download_quota(0) == (True, "")
    assert validate_monthly_download_quota(25.5) == (True, "")
    assert validate_monthly_download_quota(-1)[0] is False
    assert validate_monthly_download_quota(True)[0] is False

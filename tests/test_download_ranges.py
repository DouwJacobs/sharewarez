import asyncio
from unittest.mock import patch

import pytest

from asgi import LazyASGIApp, parse_single_byte_range
from sharewarez.async_streaming import create_async_streaming_response


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 100, None),
        ("bytes=0-9", 100, (0, 9)),
        ("bytes=10-", 100, (10, 99)),
        ("bytes=-10", 100, (90, 99)),
        ("bytes=95-200", 100, (95, 99)),
    ],
)
def test_parse_single_byte_range(header, size, expected):
    assert parse_single_byte_range(header, size) == expected


@pytest.mark.parametrize(
    "header",
    ["items=0-10", "bytes=", "bytes=100-", "bytes=20-10", "bytes=0-1,4-5", "bytes=-0"],
)
def test_parse_single_byte_range_rejects_invalid_ranges(header):
    with pytest.raises(ValueError):
        parse_single_byte_range(header, 100)


def test_async_streaming_response_reads_only_requested_bytes(tmp_path):
    source = tmp_path / "game.bin"
    source.write_bytes(b"0123456789")

    async def collect():
        chunks, headers = await create_async_streaming_response(
            str(source), source.name, chunk_size=2, start=3, length=4
        )
        return b"".join([chunk async for chunk in chunks]), headers

    with patch("sharewarez.async_streaming.log_system_event"):
        body, headers = asyncio.run(collect())
    assert body == b"3456"
    assert headers["content-length"] == "4"
    assert headers["accept-ranges"] == "bytes"


def test_stream_file_returns_partial_content(tmp_path):
    source = tmp_path / "game.bin"
    source.write_bytes(b"0123456789")
    messages = []

    async def send(message):
        messages.append(message)

    with patch("sharewarez.async_streaming.log_system_event"), patch("asgi.log_system_event"):
        asyncio.run(
            LazyASGIApp()._stream_file(
                send,
                str(source),
                source.name,
                {"headers": [(b"range", b"bytes=3-6")]},
            )
        )

    start = messages[0]
    headers = dict(start["headers"])
    body = b"".join(message.get("body", b"") for message in messages[1:])
    assert start["status"] == 206
    assert headers[b"content-range"] == b"bytes 3-6/10"
    assert headers[b"content-length"] == b"4"
    assert body == b"3456"


def test_stream_file_rejects_unsatisfiable_range(tmp_path):
    source = tmp_path / "game.bin"
    source.write_bytes(b"0123456789")
    messages = []

    async def send(message):
        messages.append(message)

    asyncio.run(
        LazyASGIApp()._stream_file(
            send,
            str(source),
            source.name,
            {"headers": [(b"range", b"bytes=10-")]},
        )
    )

    assert messages[0]["status"] == 416
    assert dict(messages[0]["headers"])[b"content-range"] == b"bytes */10"

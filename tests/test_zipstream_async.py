import asyncio
import io
import time
import zipfile

from sharewarez.utils import zipstream as zipstream_utils


async def _collect(source_path):
    return b''.join([
        chunk async for chunk in zipstream_utils.async_generate_zipstream_chunks(source_path)
    ])


def test_streamed_archive_is_valid_and_applies_exclusions(tmp_path):
    (tmp_path / 'game.bin').write_bytes(b'game data')
    (tmp_path / 'sharewarez.json').write_text('{}')
    excluded = tmp_path / 'updates'
    excluded.mkdir()
    (excluded / 'patch.bin').write_bytes(b'patch data')

    archive_bytes = asyncio.run(_collect(str(tmp_path)))

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.namelist() == ['game.bin']
        assert archive.read('game.bin') == b'game data'


def test_chunk_generation_does_not_block_event_loop(tmp_path, monkeypatch):
    original_next = zipstream_utils._next_zipstream_chunk

    def slow_next(iterator):
        time.sleep(0.05)
        return original_next(iterator)

    monkeypatch.setattr(zipstream_utils, '_build_zipstream', lambda *args: iter([b'a', b'b']))
    monkeypatch.setattr(zipstream_utils, '_next_zipstream_chunk', slow_next)

    async def run_download_with_heartbeat():
        ticks = 0
        download = asyncio.create_task(_collect(str(tmp_path)))
        while not download.done():
            ticks += 1
            await asyncio.sleep(0.01)
        assert await download == b'ab'
        return ticks

    assert asyncio.run(run_download_with_heartbeat()) >= 5

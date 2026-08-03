import json

from sharewarez.utils.scanning import (
    _optional_iso_date,
    _optional_nonnegative_int,
    _path_size,
    _read_update_metadata,
)


def test_reads_update_directory_metadata(tmp_path):
    update = tmp_path / 'Update 2'
    update.mkdir()
    (update / 'sharewarez.json').write_text(json.dumps({
        'title': 'Content patch',
        'version': '1.6.1170',
        'update_number': 2,
    }), encoding='utf-8')

    metadata = _read_update_metadata(str(update))

    assert metadata['title'] == 'Content patch'
    assert metadata['version'] == '1.6.1170'
    assert metadata['update_number'] == 2


def test_reads_archive_sidecar_metadata(tmp_path):
    archive = tmp_path / 'update.zip'
    archive.write_bytes(b'update')
    (tmp_path / 'update.zip.sharewarez.json').write_text(
        '{"is_cumulative": true}', encoding='utf-8'
    )

    assert _read_update_metadata(str(archive))['is_cumulative'] is True
    assert _path_size(str(archive)) == 6


def test_reads_configured_metadata_filename(tmp_path):
    update = tmp_path / 'Patch'
    update.mkdir()
    (update / 'game-info.json').write_text('{"version": "2.0"}', encoding='utf-8')

    assert _read_update_metadata(str(update), 'game-info.json')['version'] == '2.0'


def test_invalid_optional_metadata_values_are_ignored():
    assert _optional_nonnegative_int('-1') is None
    assert _optional_nonnegative_int('not-a-number') is None
    assert _optional_iso_date('not-a-date') is None


def test_update_directory_size_is_recursive(tmp_path):
    nested = tmp_path / 'update' / 'files'
    nested.mkdir(parents=True)
    (nested / 'patch.bin').write_bytes(b'12345')

    assert _path_size(str(tmp_path / 'update')) == 5

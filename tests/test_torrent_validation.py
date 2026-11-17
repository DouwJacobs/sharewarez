"""Offline parser regressions; no real torrent downloads."""
import hashlib
import pytest
from sharewarez.utils.torrent_sources import validate_magnet, validate_torrent


def encode(value):
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value, list):
        return b'l' + b''.join(map(encode, value)) + b'e'
    return b'd' + b''.join(encode(k) + encode(v) for k, v in sorted(value.items())) + b'e'


def test_magnets_accept_v1_and_v2():
    assert validate_magnet('magnet:?xt=urn:btih:' + 'A' * 40)['info_hash_v1'] == 'a' * 40
    assert validate_magnet('magnet:?xt=urn:btmh:1220' + 'b' * 64)['info_hash_v2'] == 'b' * 64


@pytest.mark.parametrize('uri', ['https://example.com/a', 'magnet:?dn=test',
                                'magnet:?xt=urn:btih:bad', 'magnet:?xt=%GG',
                                'magnet:?xt=urn:btih:' + 'a' * 40 + '&dn=%00'])
def test_invalid_magnets(uri):
    with pytest.raises(ValueError):
        validate_magnet(uri)


def test_v1_hashes_original_info_bytes():
    info = {b'name': b'game', b'length': 1, b'piece length': 16384, b'pieces': b'x' * 20}
    result = validate_torrent(encode({b'info': info}))
    assert result['info_hash_v1'] == hashlib.sha1(encode(info)).hexdigest()
    assert result['payload_bytes'] == 1


def test_v2_file_tree():
    info = {b'name': b'game', b'meta version': 2, b'piece length': 16384,
            b'file tree': {b'game.bin': {b'': {b'length': 1, b'pieces root': b'x' * 32}}}}
    result = validate_torrent(encode({b'info': info}))
    assert result['info_hash_v2'] == hashlib.sha256(encode(info)).hexdigest()


@pytest.mark.parametrize('paths', [
    [[b'foo'], [b'foo', b'bar']],
    [[b'foo', b'bar'], [b'foo']],
])
def test_v1_rejects_file_directory_collisions_in_either_order(paths):
    info = {b'name': b'game', b'piece length': 16384, b'pieces': b'x' * 20,
            b'files': [{b'length': 1, b'path': path} for path in paths]}
    with pytest.raises(ValueError, match='conflict with directory'):
        validate_torrent(encode({b'info': info}))


def test_v1_accepts_siblings_in_a_shared_directory():
    info = {b'name': b'game', b'piece length': 16384, b'pieces': b'x' * 20,
            b'files': [{b'length': 1, b'path': [b'foo', name]} for name in (b'a', b'b')]}
    assert validate_torrent(encode({b'info': info}))['payload_bytes'] == 2


def test_v2_piece_layers_verify_merkle_root():
    layer = b'a' * 32 + b'b' * 32
    root = hashlib.sha256(layer).digest()
    info = {b'name': b'game', b'meta version': 2, b'piece length': 16384,
            b'file tree': {b'game.bin': {b'': {b'length': 20000, b'pieces root': root}}}}
    assert validate_torrent(encode({b'info': info, b'piece layers': {root: layer}}))['payload_bytes'] == 20000
    with pytest.raises(ValueError, match='pieces root'):
        validate_torrent(encode({b'info': info, b'piece layers': {root: b'x' * 64}}))


def test_hybrid_file_trees_must_match():
    info = {b'name': b'game.bin', b'meta version': 2, b'piece length': 16384,
            b'length': 1, b'pieces': b'a' * 20,
            b'file tree': {b'game.bin': {b'': {b'length': 1, b'pieces root': b'x' * 32}}}}
    valid = validate_torrent(encode({b'info': info}))
    assert valid['info_hash_v1'] and valid['info_hash_v2']
    info[b'length'] = 2
    with pytest.raises(ValueError, match='Hybrid'):
        validate_torrent(encode({b'info': info}))


def test_normalized_magnets_keep_tracker_variants_distinct():
    first = validate_magnet('magnet:?xt=urn:btih:' + 'A' * 40 + '&dn=Game&tr=https%3A%2F%2Fone.example')
    reordered = validate_magnet('magnet:?tr=https%3A%2F%2Fone.example&dn=Game&xt=urn:btih:' + 'a' * 40)
    variant = validate_magnet('magnet:?xt=urn:btih:' + 'a' * 40 + '&dn=Game&tr=https%3A%2F%2Ftwo.example')
    assert first['fingerprint'] == reordered['fingerprint']
    assert first['fingerprint'] != variant['fingerprint']
    with pytest.raises(ValueError, match='conflicting'):
        validate_magnet('magnet:?xt=urn:btih:' + 'a' * 40 + '&xt=urn:btih:' + 'b' * 40)


def test_validation_never_opens_network_connections(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('Torrent metadata validation must remain offline')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    assert validate_magnet('magnet:?xt=urn:btih:' + 'a' * 40 + '&tr=https://tracker.example/announce')
    info = {b'name': b'game', b'length': 1, b'piece length': 16384, b'pieces': b'x' * 20}
    assert validate_torrent(encode({b'announce': b'https://tracker.example/announce', b'info': info}))


@pytest.mark.parametrize('data', [b'', b'd4:infode', b'999999999:small', b'letrailing',
                                  b'd1:ai1e1:ai2ee', b'l' * 66 + b'e' * 66])
def test_malformed_bencoding(data):
    with pytest.raises(ValueError):
        validate_torrent(data)


@pytest.mark.parametrize('changes', [{b'private': 1}, {b'name': b'../bad'},
                                   {b'length': -1}, {b'pieces': b'x'}])
def test_private_unsafe_and_inconsistent_torrents(changes):
    info = {b'name': b'game', b'length': 1, b'piece length': 16384, b'pieces': b'x' * 20}
    info.update(changes)
    with pytest.raises(ValueError):
        validate_torrent(encode({b'info': info}))

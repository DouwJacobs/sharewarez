"""Offline, bounded validation of public torrent source metadata."""
import base64
import hashlib
import re
from urllib.parse import parse_qsl, urlsplit, urlencode

MAX_TORRENT_BYTES = 10 * 1024 * 1024


def validate_magnet(uri):
    uri = uri.strip()
    if len(uri.encode('utf-8')) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in uri):
        raise ValueError('Magnet is too long or contains control characters.')
    if re.search(r'%(?![0-9a-fA-F]{2})', uri):
        raise ValueError('Invalid magnet encoding.')
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != 'magnet' or parsed.netloc or parsed.path or parsed.fragment:
        raise ValueError('Enter a magnet link with a supported info hash.')
    hashes = {}
    parameters = parse_qsl(parsed.query, keep_blank_values=True, errors='strict', max_num_fields=256)
    for key, value in parameters:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Invalid magnet parameter.')
        if key != 'xt':
            continue
        if value.lower().startswith('urn:btih:'):
            digest = value[9:]
            if re.fullmatch(r'[a-fA-F0-9]{40}', digest):
                digest = digest.lower()
            elif re.fullmatch(r'[a-zA-Z2-7]{32}', digest):
                digest = base64.b32decode(digest.upper()).hex()
            else:
                raise ValueError('Invalid v1 info hash.')
            if hashes.get('info_hash_v1', digest) != digest:
                raise ValueError('Magnet contains conflicting content identifiers.')
            hashes['info_hash_v1'] = digest
        elif re.fullmatch(r'urn:btmh:1220[0-9a-fA-F]{64}', value, flags=re.IGNORECASE):
            if hashes.get('info_hash_v2', value[13:].lower()) != value[13:].lower():
                raise ValueError('Magnet contains conflicting content identifiers.')
            hashes['info_hash_v2'] = value[13:].lower()
        else:
            raise ValueError('Unsupported magnet identifier.')
    if not hashes:
        raise ValueError('Magnet must contain a supported xt info hash.')
    normalized = [(key, value) for key, value in parameters if key != 'xt']
    if hashes.get('info_hash_v1'):
        normalized.append(('xt', 'urn:btih:' + hashes['info_hash_v1']))
    if hashes.get('info_hash_v2'):
        normalized.append(('xt', 'urn:btmh:1220' + hashes['info_hash_v2']))
    fingerprint = hashlib.sha256(urlencode(sorted(normalized)).encode()).hexdigest()
    return dict(hashes, magnet_uri=uri, fingerprint=fingerprint)


class _Decoder:
    def __init__(self, data):
        self.data, self.pos, self.items, self.info_bytes = data, 0, 0, None

    def read(self, depth=0):
        self.items += 1
        if depth > 64 or self.items > 100000 or self.pos >= len(self.data):
            raise ValueError('Torrent structure exceeds limits or is incomplete.')
        start = self.pos
        token = self.data[self.pos:self.pos + 1]
        self.pos += 1
        if token == b'i':
            end = self.data.find(b'e', self.pos)
            raw = self.data[self.pos:end]
            if end < 0 or len(raw) > 20 or not re.fullmatch(rb'0|-?[1-9][0-9]*', raw):
                raise ValueError('Invalid torrent integer.')
            self.pos = end + 1
            return int(raw)
        if token in (b'l', b'd'):
            result = [] if token == b'l' else {}
            previous = None
            while self.data[self.pos:self.pos + 1] != b'e':
                key = self.read(depth + 1)
                if token == b'l':
                    result.append(key)
                    continue
                if not isinstance(key, bytes) or (previous is not None and key <= previous):
                    raise ValueError('Torrent dictionary keys must be unique and sorted.')
                previous = key
                value_start = self.pos
                result[key] = self.read(depth + 1)
                if depth == 0 and key == b'info':
                    self.info_bytes = self.data[value_start:self.pos]
            self.pos += 1
            return result
        self.pos = start
        colon = self.data.find(b':', start, start + 12)
        raw = self.data[start:colon]
        if colon < 0 or not re.fullmatch(rb'0|[1-9][0-9]*', raw):
            raise ValueError('Invalid torrent string length.')
        length = int(raw)
        self.pos = colon + 1 + length
        if self.pos > len(self.data):
            raise ValueError('Truncated torrent string.')
        return self.data[colon + 1:self.pos]


def _component(value):
    if not isinstance(value, bytes) or not value or value in (b'.', b'..') or any(c in value for c in (b'/', b'\\', b':', b'\x00')):
        raise ValueError('Unsafe torrent file path.')
    value.decode('utf-8', errors='strict')
    if any(byte < 32 or byte == 127 for byte in value):
        raise ValueError('Invalid torrent filename characters.')


def _length(value):
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise ValueError('Invalid torrent payload size.')
    return value


def validate_torrent(data):
    if not data or len(data) > MAX_TORRENT_BYTES:
        raise ValueError('Torrent files must be between 1 byte and 10 MiB.')
    decoder = _Decoder(data)
    root = decoder.read()
    if decoder.pos != len(data) or not isinstance(root, dict) or not isinstance(root.get(b'info'), dict):
        raise ValueError('Invalid torrent metainfo.')
    info = root[b'info']
    if b'private' in info and (type(info[b'private']) is not int or info[b'private'] != 0):
        raise ValueError('Only public torrents are supported.')
    _component(info.get(b'name'))
    piece_length = info.get(b'piece length')
    if type(piece_length) is not int or piece_length <= 0:
        raise ValueError('Invalid torrent piece length.')
    result = {'file_sha256': hashlib.sha256(data).hexdigest(), 'file_bytes': len(data)}
    total = 0
    v1_files = {}
    if b'pieces' in info:
        if b'files' in info:
            if b'length' in info or not isinstance(info[b'files'], list) or not info[b'files']:
                raise ValueError('Invalid torrent file list.')
            seen = set()
            directories = set()
            for file in info[b'files']:
                if not isinstance(file, dict) or not isinstance(file.get(b'path'), list) or not file[b'path']:
                    raise ValueError('Invalid torrent file path.')
                for part in file[b'path']:
                    _component(part)
                path = tuple(file[b'path'])
                if path in seen:
                    raise ValueError('Duplicate torrent file path.')
                parents = [path[:index] for index in range(1, len(path))]
                if path in directories or any(parent in seen for parent in parents):
                    raise ValueError('Torrent file paths conflict with directory paths.')
                seen.add(path)
                directories.update(parents)
                length = _length(file.get(b'length'))
                total += length
                attributes = file.get(b'attr', b'')
                if not isinstance(attributes, bytes):
                    raise ValueError('Invalid torrent file attributes.')
                if b'p' not in attributes:
                    v1_files[path] = length
        else:
            total = _length(info.get(b'length'))
            v1_files[(info[b'name'],)] = total
        pieces = info[b'pieces']
        if not isinstance(pieces, bytes) or len(pieces) != 20 * ((total + piece_length - 1) // piece_length):
            raise ValueError('Invalid torrent piece hashes.')
        result['info_hash_v1'] = hashlib.sha1(decoder.info_bytes).hexdigest()
    if info.get(b'meta version') == 2:
        if piece_length < 16384 or piece_length & (piece_length - 1):
            raise ValueError('Invalid v2 piece length.')
        layers = root.get(b'piece layers', {})
        if not isinstance(layers, dict):
            raise ValueError('Invalid v2 piece layers.')
        used_layers = set()
        v2_files = {}
        def walk(tree, path=()):
            if not isinstance(tree, dict) or not tree:
                raise ValueError('Invalid v2 file tree.')
            size = 0
            for name, child in tree.items():
                if name == b'':
                    if len(tree) != 1 or not isinstance(child, dict):
                        raise ValueError('Invalid v2 file leaf.')
                    length = _length(child.get(b'length'))
                    digest = child.get(b'pieces root')
                    if length and (not isinstance(digest, bytes) or len(digest) != 32):
                        raise ValueError('Invalid v2 pieces root.')
                    if length > piece_length:
                        layer = layers.get(digest)
                        if not isinstance(layer, bytes) or len(layer) != 32 * ((length + piece_length - 1) // piece_length):
                            raise ValueError('Invalid v2 piece layer.')
                        used_layers.add(digest)
                        nodes = [layer[index:index + 32] for index in range(0, len(layer), 32)]
                        zero = bytes(32)
                        blocks = piece_length // 16384
                        while blocks > 1:
                            zero = hashlib.sha256(zero + zero).digest()
                            blocks //= 2
                        nodes += [zero] * ((1 << (len(nodes) - 1).bit_length()) - len(nodes))
                        while len(nodes) > 1:
                            nodes = [hashlib.sha256(nodes[i] + nodes[i + 1]).digest() for i in range(0, len(nodes), 2)]
                        if nodes[0] != digest:
                            raise ValueError('V2 piece layer does not match the pieces root.')
                    v2_files[path] = length
                    size += length
                else:
                    _component(name)
                    size += walk(child, path + (name,))
            return size
        v2_total = walk(info.get(b'file tree'))
        if set(layers) != used_layers:
            raise ValueError('Unexpected v2 piece layers.')
        if v1_files and v1_files != v2_files:
            raise ValueError('Hybrid torrent file trees do not match.')
        total = v2_total
        result['info_hash_v2'] = hashlib.sha256(decoder.info_bytes).hexdigest()
    elif b'meta version' in info:
        raise ValueError('Unsupported torrent version.')
    if not any(key in result for key in ('info_hash_v1', 'info_hash_v2')):
        raise ValueError('Torrent has no supported content hashes.')
    result['payload_bytes'] = _length(total)
    result['fingerprint'] = result['file_sha256']
    return result

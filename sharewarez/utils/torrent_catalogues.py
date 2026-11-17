"""Bounded public Hydra catalogue retrieval and deliberately conservative matching."""
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import re
import socket
from threading import Lock
from time import monotonic
import unicodedata
from urllib.parse import urljoin, urlsplit
from sharewarez.utils.torrent_sources import validate_magnet

import urllib3

MAX_CATALOGUE_BYTES = 20 * 1024 * 1024
MAX_CATALOGUE_ENTRIES = 100000
CACHE_TTL_SECONDS = 900
_cache = {}
_cache_lock = Lock()


class CatalogueError(ValueError):
    """A source could not be safely fetched or understood."""


def validate_catalogue_url(value):
    """Syntax validation only; DNS and public-address checks happen on every fetch."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise CatalogueError('Source URL must contain 1–2048 characters.')
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.fragment or parsed.port == 0
                or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError()
        parsed.port
        host = parsed.hostname.encode('idna').decode('ascii')
        if not host or '..' in host:
            raise ValueError()
    except (ValueError, UnicodeError) as error:
        raise CatalogueError('Use an HTTP(S) source URL without credentials or a fragment.') from error
    return value


def _public_addresses(host, port):
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise CatalogueError('Source must resolve only to public internet addresses.')
        return sorted(addresses, key=lambda address: (ipaddress.ip_address(address).version, address))
    except (socket.gaierror, ValueError) as error:
        raise CatalogueError('Source hostname could not be resolved to a public address.') from error


def fetch_bytes(url, max_bytes):
    """Pin each connection to a checked address, retaining TLS hostname verification.

    Proxies, automatic redirects, retries and compression are disabled. Each
    redirect is resolved and checked independently, including its DNS results.
    """
    url = validate_catalogue_url(url)
    deadline = monotonic() + 45
    for redirect in range(4):
        if monotonic() > deadline:
            raise CatalogueError('Source fetch exceeded its time limit.')
        parsed = urlsplit(url)
        host = parsed.hostname.encode('idna').decode('ascii')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        address = _public_addresses(host, port)[0]
        pool_type = urllib3.HTTPSConnectionPool if parsed.scheme == 'https' else urllib3.HTTPConnectionPool
        options = {'assert_hostname': host, 'server_hostname': host} if parsed.scheme == 'https' else {}
        pool = pool_type(address, port=port, timeout=urllib3.Timeout(connect=5, read=10), **options)
        response = None
        try:
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            authority = f'[{host}]' if ':' in host else host
            if parsed.port:
                authority += ':' + str(port)
            response = pool.urlopen('GET', target, headers={
                'Host': authority, 'Accept-Encoding': 'identity',
                'User-Agent': 'GameLibrary-Catalogues/1',
            }, redirect=False, retries=False, preload_content=False)
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get('Location')
                if not location or redirect == 3:
                    raise CatalogueError('Source redirected too many times or omitted its destination.')
                url = validate_catalogue_url(urljoin(url, location))
                continue
            if response.status != 200:
                raise CatalogueError(f'Source returned HTTP {response.status}.')
            if response.headers.get('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                raise CatalogueError('Source returned unsupported compressed content.')
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise CatalogueError('Source response exceeds the allowed size.')
            chunks, size = [], 0
            while True:
                if monotonic() > deadline:
                    raise CatalogueError('Source fetch exceeded its time limit.')
                chunk = response.read(min(65536, max_bytes + 1 - size), decode_content=False)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise CatalogueError('Source response exceeds the allowed size.')
                chunks.append(chunk)
            return b''.join(chunks)
        except (urllib3.exceptions.HTTPError, OSError, UnicodeError) as error:
            raise CatalogueError('Source could not be fetched; check its availability and certificate.') from error
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise CatalogueError('Source redirect limit exceeded.')


def parse_catalogue(data):
    if isinstance(data, (bytes, str)):
        if len(data) > MAX_CATALOGUE_BYTES:
            raise CatalogueError('Catalogue exceeds 20 MiB.')
        try:
            data = json.loads(data)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise CatalogueError('Source did not return valid JSON; browser verification pages are unsupported.') from error
    if not isinstance(data, dict) or not isinstance(data.get('name'), str) or not data['name'].strip():
        raise CatalogueError('Catalogue requires a source name.')
    downloads = data.get('downloads')
    if not isinstance(downloads, list) or len(downloads) > MAX_CATALOGUE_ENTRIES:
        raise CatalogueError('Catalogue requires a downloads list of at most 100,000 entries.')
    result = []
    for entry in downloads:
        if (not isinstance(entry, dict) or not isinstance(entry.get('title'), str)
                or not entry['title'].strip() or len(entry['title']) > 1024
                or not isinstance(entry.get('uris'), list) or len(entry['uris']) > 30
                or any(not isinstance(uri, str) or len(uri) > 16384 for uri in entry['uris'])):
            raise CatalogueError('Catalogue contains an invalid title or URI list.')
        uris = []
        for uri in entry['uris']:
            uri = uri.strip()
            if uri.startswith('magnet:'):
                try:
                    validate_magnet(uri)
                except (ValueError, UnicodeError):
                    continue
                uris.append(uri)
            elif uri.startswith(('https://', 'http://')):
                try:
                    if urlsplit(uri).path.lower().endswith('.torrent'):
                        uris.append(validate_catalogue_url(uri))
                except ValueError as error:
                    raise CatalogueError('Catalogue contains an invalid torrent URL.') from error
        if uris:
            result.append({'title': entry['title'].strip(), 'uris': list(dict.fromkeys(uris)),
                           'uploadDate': str(entry.get('uploadDate') or '')[:100],
                           'fileSize': str(entry.get('fileSize') or '')[:100]})
    return {'name': data['name'].strip()[:160], 'downloads': result}


def fetch_catalogue(url, force_refresh=False, *, force=False):
    url = validate_catalogue_url(url)
    with _cache_lock:
        cached = _cache.get(url)
        if cached and cached[0] > monotonic() and not (force or force_refresh):
            return deepcopy(cached[1])
    catalogue = parse_catalogue(fetch_bytes(url, MAX_CATALOGUE_BYTES))
    catalogue['source_url'] = url
    with _cache_lock:
        if len(_cache) >= 5:
            _cache.pop(next(iter(_cache)))
        _cache[url] = (monotonic() + CACHE_TTL_SECONDS, catalogue)
    return deepcopy(catalogue)


def _title_key(title, release=False):
    title = unicodedata.normalize('NFKC', title).casefold().strip()
    if release:
        title = re.sub(r'\s*\[(?:fitgirl|dodi)(?:\s+repack)?(?:,[^\]]*)?\]\s*$', '', title)
        # Edition words in the title remain part of its identity. Edition words
        # inside a release suffix also prevent it being silently discarded.
        parts = re.split(r'\s+(?:[–—-]\s+|\()v\d+(?:\.\d+)', title, maxsplit=1)
        if len(parts) == 2 and not re.search(r'\b(?:edition|remaster(?:ed)?|remake)\b', parts[1]):
            title = parts[0]
    return ''.join(c for c in title if c.isalnum())


def _release_keys(title):
    # Spaced slashes separate catalogue aliases; version slashes have no spaces.
    # Only compare complete aliases, never arbitrary title prefixes/substrings.
    release = _title_key(title, release=True)
    cleaned = re.sub(r'\s*\[(?:fitgirl|dodi)(?:\s+repack)?(?:,[^\]]*)?\]\s*$', '', title, flags=re.I)
    parts = re.split(r'\s+(?:[–—-]\s+|\()v\d+(?:\.\d+)', cleaned, maxsplit=1, flags=re.I)
    if len(parts) == 2 and not re.search(r'\b(?:edition|remaster(?:ed)?|remake)\b', parts[1], flags=re.I):
        cleaned = parts[0]
    return {release, *(_title_key(alias) for alias in re.split(r'\s+/\s+', cleaned))}


def _upload_date(value):
    try:
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        # Date-only and unzoned catalogue timestamps are interpreted as UTC.
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def match_catalogues(title, catalogues, *, prefer_latest_upload=False):
    key = _title_key(title)
    matches = []
    seen = {}
    if key:
        for catalogue in catalogues:
            for entry in catalogue['downloads']:
                if key not in _release_keys(entry['title']):
                    continue
                signature = (entry['title'].casefold(), tuple(sorted(entry['uris'])))
                if signature in seen:
                    existing = matches[seen[signature]]
                    new_date = _upload_date(entry.get('uploadDate'))
                    old_date = _upload_date(existing.get('uploadDate'))
                    if new_date is not None and (old_date is None or new_date > old_date):
                        matches[seen[signature]] = dict(entry, source_name=catalogue['name'],
                            source_url=catalogue.get('source_url', ''))
                    continue
                seen[signature] = len(matches)
                matches.append(dict(entry, source_name=catalogue['name'],
                                    source_url=catalogue.get('source_url', '')))
    if len(matches) == 1:
        return {'status': 'matched', 'entry': matches[0]}
    if len(matches) > 1 and prefer_latest_upload:
        dates = [_upload_date(entry.get('uploadDate')) for entry in matches]
        if all(date is not None for date in dates):
            latest = max(dates)
            newest = [entry for entry, date in zip(matches, dates) if date == latest]
            if len(newest) == 1:
                return {'status': 'matched', 'entry': newest[0], 'selection_reason': 'latest_upload'}
    return {'status': 'ambiguous' if matches else 'not_found', 'entry': None,
            'candidates': matches[:10]}

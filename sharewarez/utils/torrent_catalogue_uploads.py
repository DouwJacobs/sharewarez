"""Private, database-backed catalogue snapshots with content-addressed identity."""
import hashlib

from sharewarez import db
from sharewarez.models import UploadedTorrentCatalogue
from sharewarez.utils.torrent_catalogues import parse_catalogue


def uploaded_metadata():
    record = db.session.get(UploadedTorrentCatalogue, 1, populate_existing=True)
    if record is None:
        return None
    return {'name': record.name, 'filename': record.filename, 'sha256': record.sha256,
            'entry_count': record.entry_count, 'uploaded_at': record.uploaded_at.isoformat(),
            'source_url': 'uploaded:' + record.sha256}


def with_uploaded_catalogue(settings):
    return {**settings, '_uploaded_catalogue': uploaded_metadata()}


def source_identifiers(settings):
    sources = settings.get('torrentCatalogueUrls', '').split()
    uploaded = settings.get('_uploaded_catalogue')
    return sources + ([uploaded['source_url']] if uploaded else [])


def read_uploaded_catalogue(expected):
    record = db.session.get(UploadedTorrentCatalogue, 1, populate_existing=True)
    if record is None or record.sha256 != expected['sha256']:
        raise ValueError('The uploaded catalogue changed. Retry source lookup.')
    content = record.content
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise ValueError('The uploaded catalogue failed its integrity check. Upload it again.')
    catalogue = parse_catalogue(content)
    catalogue['source_url'] = 'uploaded:' + record.sha256
    return catalogue

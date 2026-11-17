"""Shared validation and attachment persistence for forms and source routes."""
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from sharewarez.models import GameTorrentSource
from sharewarez.utils.torrent_sources import validate_magnet, validate_torrent, MAX_TORRENT_BYTES
from sharewarez.utils.torrent_storage import store_attachment, attachment_path, acquire_source_mutation_lock
from sqlalchemy import select, or_
from sharewarez import db


class SourceRowError(ValueError):
    def __init__(self, index, message):
        self.row_index = index
        super().__init__(f'Source {index}: {message}')


def confirm_hash_variants(prepared, confirmed=False, exclude_id=None, game_uuid=None):
    """Warn before retaining alternate tracker data or cross-game hash matches."""
    seen = {}
    for values, _ in prepared:
        conditions = [getattr(GameTorrentSource, key) == values[key]
                      for key in ('info_hash_v1', 'info_hash_v2') if values.get(key)]
        matches = db.session.execute(select(GameTorrentSource).where(or_(*conditions))).scalars().all()
        for match in matches:
            if match.id == exclude_id:
                continue
            if (match.fingerprint != values['fingerprint'] or match.game_uuid != game_uuid) and not confirmed:
                raise ValueError('Matching torrent content already exists with different source data. Confirm keeping a separate source, or replace the existing source.')
        for key in ('info_hash_v1', 'info_hash_v2'):
            digest = values.get(key)
            if digest and digest in seen and seen[digest] != values['fingerprint'] and not confirmed:
                raise ValueError('New sources refer to matching content. Confirm keeping separate sources or remove the duplicate row.')
            if digest:
                seen[digest] = values['fingerprint']


def prepare_source(label, magnet='', upload=None, public=False):
    if not isinstance(label, str) or not isinstance(magnet, str):
        raise ValueError('Source labels and magnet links must be text.')
    label = (label or '').strip()
    if not label or len(label) > 160:
        raise ValueError('Each source needs a label of 1–160 characters.')
    if not public:
        raise ValueError('Confirm this is a public source without personal tracker credentials.')
    magnet = (magnet or '').strip()
    has_file = upload is not None and bool(upload.filename)
    if bool(magnet) == has_file:
        raise ValueError('Provide either a magnet link or a torrent file for each source.')
    if magnet:
        return dict(validate_magnet(magnet), label=label, kind='magnet'), None
    if not upload.filename.lower().endswith('.torrent'):
        raise ValueError('Upload a .torrent file.')
    data = upload.stream.read(MAX_TORRENT_BYTES + 1)
    if len(data) > MAX_TORRENT_BYTES:
        raise RequestEntityTooLarge('Torrent uploads must not exceed 10 MiB.')
    values = validate_torrent(data)
    filename = secure_filename(upload.filename)
    filename = (filename[:-8][:247] + '.torrent') if filename.lower().endswith('.torrent') and filename[:-8] else 'game.torrent'
    values.update(label=label, kind='torrent', original_filename=filename)
    return values, data


def prepare_form_sources(form, files, game_uuid=None):
    labels = form.getlist('source_label')
    magnets = form.getlist('source_magnet')
    uploads = files.getlist('source_file')
    if len(labels) > 30:
        raise ValueError('Add at most 30 sources at a time.')
    result = []
    for index, label in enumerate(labels):
        magnet = magnets[index] if index < len(magnets) else ''
        upload = uploads[index] if index < len(uploads) else None
        if not label.strip() and not magnet.strip() and not (upload and upload.filename):
            continue
        try:
            result.append(prepare_source(label, magnet, upload, form.get('sources_public') == '1'))
        except (ValueError, UnicodeError) as exc:
            raise SourceRowError(index + 1, str(exc)) from exc
    fingerprints = [values['fingerprint'] for values, _ in result]
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError('The same source was entered more than once.')
    confirm_hash_variants(result, form.get('sources_variants_confirm') == '1', game_uuid=game_uuid)
    return result


def attach_prepared(game, prepared, actor_id):
    """Caller commits; discard created files when its transaction fails."""
    keys = []
    try:
        acquire_source_mutation_lock()
        db.session.add(game)
        db.session.flush()  # Assign a new game's UUID before locking its row.
        acquire_source_mutation_lock(game.uuid)
        # Another transaction may have attached sources while this caller waited.
        db.session.expire(game, ['torrent_sources'])
        for values, data in prepared:
            values = dict(values)
            if any(source.fingerprint == values['fingerprint'] for source in game.torrent_sources):
                continue
            if data is not None:
                values['storage_key'] = store_attachment(data)
                keys.append(values['storage_key'])
            game.torrent_sources.append(GameTorrentSource(**values, created_by=actor_id))
    except Exception:
        discard_attachments(keys)
        raise
    return keys


def discard_attachments(keys):
    for key in keys:
        try:
            attachment_path(key).unlink(missing_ok=True)
        except OSError:
            pass  # Unreferenced-file maintenance retries cleanup.

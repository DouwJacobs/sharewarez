"""Run an actual PostgreSQL and attachment round trip using disposable databases."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask
from sqlalchemy import create_engine, text
from sharewarez.backups import create_backup, restore_backup, verify_backup
from sharewarez.utils.torrent_storage import verified_attachment
from types import SimpleNamespace

source = os.environ['TORRENT_BACKUP_SOURCE_URL']
target = os.environ['TORRENT_BACKUP_TARGET_URL']
if not source.endswith('/gamelibrary_torrent_preview') or not target.endswith('/gamelibrary_torrent_restore_test'):
    raise RuntimeError('Only the disposable torrent preview and restore databases are allowed.')
original_directory = '/tmp/gamelibrary-torrent-preview-files'
restored_directory = '/tmp/gamelibrary-torrent-restored-files'
os.environ['TORRENT_STORAGE_DIR'] = original_directory
dump = create_backup(source, '/tmp/gamelibrary-torrent-roundtrip', reason='torrent-roundtrip')
assert verify_backup(dump)
os.environ['TORRENT_STORAGE_DIR'] = restored_directory
restore_backup(dump, target, confirmation='gamelibrary_torrent_restore_test')
with create_engine(source).connect() as connection:
    source_count = connection.execute(text('SELECT count(*) FROM game_torrent_sources')).scalar_one()
with create_engine(target).connect() as connection:
    assert connection.execute(text('SELECT count(*) FROM game_torrent_sources')).scalar_one() == source_count
    files = connection.execute(text("SELECT storage_key, file_bytes, file_sha256 FROM game_torrent_sources WHERE kind='torrent' ")).mappings().all()
    assert files, 'The preview must contain an uploaded torrent fixture.'
app = Flask(__name__)
app.config['TORRENT_STORAGE_DIR'] = restored_directory
with app.app_context():
    for file in files:
        assert verified_attachment(SimpleNamespace(**file))
print(f'Actual PostgreSQL restore preserved {source_count} sources and verified {len(files)} torrent attachments.')

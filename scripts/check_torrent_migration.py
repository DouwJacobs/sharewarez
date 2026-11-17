"""Exercise revision 36 against an isolated PostgreSQL test database."""
import importlib.util
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sharewarez import db
from sharewarez.models import Game, Library
from sharewarez.platform import LibraryPlatform

url = os.environ['TORRENT_MIGRATION_DATABASE_URL']
if not url.rsplit('/', 1)[-1].endswith('torrent_migration_test'):
    raise RuntimeError('Requires an isolated torrent_migration_test database.')
engine = create_engine(url)
db.metadata.create_all(engine)
game_uuid = str(uuid4())
with Session(engine) as session:
    library = Library(name='Migration fixture', platform=LibraryPlatform.PCWIN)
    session.add(Game(uuid=game_uuid, name='Existing pathless game', library=library))
    session.commit()
with engine.begin() as connection:
    connection.execute(text('DROP TABLE game_torrent_sources'))
    connection.execute(text('ALTER TABLE unmatched_folders DROP COLUMN candidate_game_uuid CASCADE'))
    spec = importlib.util.spec_from_file_location('torrent_migration',
        Path(__file__).resolve().parents[1] / 'migrations/versions/20261117_36_torrent_sources.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        assert 'game_torrent_sources' in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT full_disk_path FROM games WHERE uuid=:uuid'), {'uuid': game_uuid}).scalar() is None
        connection.execute(text("""INSERT INTO game_torrent_sources
            (id, game_uuid, kind, label, magnet_uri, info_hash_v1, fingerprint, created_at, updated_at, revision)
            VALUES (:id, :game, 'magnet', 'Release', :magnet, :hash, :fingerprint, now(), now(), 1)"""),
            {'id': str(uuid4()), 'game': game_uuid, 'magnet': 'magnet:?xt=urn:btih:' + 'a' * 40,
             'hash': 'a' * 40, 'fingerprint': 'b' * 64})
        try:
            migration.downgrade()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Downgrade discarded source data')
        connection.execute(text('DELETE FROM game_torrent_sources'))
        migration.downgrade()
        migration.upgrade()
print('Torrent migration upgrade, preservation, downgrade guard, and empty downgrade passed.')

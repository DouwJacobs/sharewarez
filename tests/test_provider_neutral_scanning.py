from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sharewarez.models import Game, GameExternalIdentity, GlobalSettings, Image, Library
from sharewarez.platform import LibraryPlatform
from sharewarez.utils.game_core import (
    create_game_instance_from_metadata,
    retrieve_and_save_game,
)
from sharewarez.utils.scanning import refresh_images_in_background


def _rawg_metadata(external_id='3498'):
    return {
        'provider': 'rawg',
        'provider_game_id': external_id,
        'provider_url': 'https://rawg.io/games/grand-theft-auto-v',
        'game_name': 'Grand Theft Auto V',
        'summary': 'A game summary',
        'first_release_date': datetime(2013, 9, 17, tzinfo=timezone.utc),
        'rating': 4.5,
        'rating_count': 100,
        'website': 'https://example.test/gta-v',
        'cover_url': 'https://media.rawg.io/gta-v.jpg',
        'genres': ['Action'],
        'platforms': ['PC'],
        'developers': ['Rockstar North'],
        'publishers': ['Rockstar Games'],
    }


def _library(db_session):
    library = Library(
        uuid=str(uuid4()), name=f'Provider scan {uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.flush()
    return library


def test_normalized_game_creation_persists_identity_and_media(db_session):
    library = _library(db_session)
    external_id = f'rawg-{uuid4().hex}'

    game = create_game_instance_from_metadata(
        _rawg_metadata(external_id), f'/games/{external_id}', 1234, library.uuid,
    )
    db_session.commit()

    identity = db_session.query(GameExternalIdentity).filter_by(
        game_uuid=game.uuid,
    ).one()
    image = db_session.query(Image).filter_by(game_uuid=game.uuid).one()
    assert game.igdb_id is None
    assert (identity.provider, identity.external_id, identity.canonical) == (
        'rawg', external_id, True,
    )
    assert (image.provider, image.provider_image_id, image.source_url) == (
        'rawg', 'https://media.rawg.io/gta-v.jpg',
        'https://media.rawg.io/gta-v.jpg',
    )


def test_folder_scan_accepts_ordered_rawg_fallback(db_session, tmp_path):
    library = _library(db_session)
    settings = db_session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings(settings={})
        db_session.add(settings)
    db_session.commit()
    metadata = _rawg_metadata(f'rawg-{uuid4().hex}')
    rawg = SimpleNamespace(fetch_game=lambda _external_id: metadata)
    registry = SimpleNamespace(
        providers={'rawg': rawg},
        search_games=lambda _term: SimpleNamespace(
            results=[metadata], provider='rawg', error=None,
        ),
    )

    with (
        patch(
            'sharewarez.utils.game_core.build_metadata_provider_registry',
            return_value=registry,
        ),
        patch('sharewarez.utils.game_core.get_folder_size_in_bytes_updates', return_value=42),
        patch('sharewarez.utils.game_core.read_first_nfo_content', return_value=None),
    ):
        game = retrieve_and_save_game(
            'Grand Theft Auto V', str(tmp_path), library_uuid=library.uuid,
            settings={
                'use_local_metadata': False,
                'write_local_metadata': False,
                'use_local_images': False,
                'local_metadata_filename': 'sharewarez.json',
            },
        )

    assert game.name == 'Grand Theft Auto V'
    assert game.external_identities[0].provider == 'rawg'


def test_rawg_canonical_identity_drives_media_refresh(app, db_session, tmp_path):
    library = _library(db_session)
    external_id = f'rawg-{uuid4().hex}'
    game = Game(name='RAWG media game', library_uuid=library.uuid)
    game.external_identities.append(GameExternalIdentity(
        provider='rawg', external_id=external_id, canonical=True,
    ))
    db_session.add(game)
    db_session.commit()
    app.config['IMAGE_SAVE_PATH'] = str(tmp_path)
    adapter = SimpleNamespace(fetch_media=lambda _external_id: ({
        'cover': 'https://media.rawg.io/cover.jpg',
        'screenshots': ['https://media.rawg.io/shot.jpg'],
        'artworks': [],
    }, None))
    registry = SimpleNamespace(providers={'rawg': adapter})

    with (
        patch(
            'sharewarez.utils.scanning.build_metadata_provider_registry',
            return_value=registry,
        ),
        patch('sharewarez.utils.functions.download_image', return_value=True),
    ):
        result = refresh_images_in_background(game.uuid)

    images = db_session.query(Image).filter_by(game_uuid=game.uuid).all()
    assert result == (True, None)
    assert {(image.provider, image.image_type) for image in images} == {
        ('rawg', 'cover'), ('rawg', 'screenshot'),
    }
    assert all(image.is_downloaded for image in images)

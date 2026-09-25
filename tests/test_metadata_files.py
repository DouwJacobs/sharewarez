from sharewarez.metadata_files import (
    DEFAULT_LOCAL_METADATA_FILENAME,
    LEGACY_LOCAL_METADATA_FILENAME,
    is_local_metadata_filename,
    metadata_filename_candidates,
)


def test_default_metadata_filename_prefers_game_library_name():
    assert metadata_filename_candidates() == (
        DEFAULT_LOCAL_METADATA_FILENAME,
        LEGACY_LOCAL_METADATA_FILENAME,
    )


def test_legacy_metadata_filename_falls_back_to_current_name():
    assert metadata_filename_candidates(LEGACY_LOCAL_METADATA_FILENAME) == (
        LEGACY_LOCAL_METADATA_FILENAME,
        DEFAULT_LOCAL_METADATA_FILENAME,
    )


def test_custom_metadata_filename_has_no_implicit_fallback():
    assert metadata_filename_candidates('game-info.json') == ('game-info.json',)


def test_standard_metadata_filename_detection_is_case_insensitive():
    assert is_local_metadata_filename('GameLibrary.JSON')
    assert is_local_metadata_filename('Sharewarez.JSON')
    assert not is_local_metadata_filename('notes.json')

"""Stable filenames used for local game metadata."""


DEFAULT_LOCAL_METADATA_FILENAME = 'gamelibrary.json'
LEGACY_LOCAL_METADATA_FILENAME = 'sharewarez.json'
LOCAL_METADATA_FILENAMES = frozenset({
    DEFAULT_LOCAL_METADATA_FILENAME,
    LEGACY_LOCAL_METADATA_FILENAME,
})


def metadata_filename_candidates(filename: str | None = None) -> tuple[str, ...]:
    """Return a configured filename plus its standard compatibility counterpart."""
    primary = filename or DEFAULT_LOCAL_METADATA_FILENAME
    normalized = primary.lower()
    if normalized == DEFAULT_LOCAL_METADATA_FILENAME:
        return primary, LEGACY_LOCAL_METADATA_FILENAME
    if normalized == LEGACY_LOCAL_METADATA_FILENAME:
        return primary, DEFAULT_LOCAL_METADATA_FILENAME
    return (primary,)


def is_local_metadata_filename(filename: str) -> bool:
    """Return whether a basename is a current or legacy metadata filename."""
    return filename.lower() in LOCAL_METADATA_FILENAMES

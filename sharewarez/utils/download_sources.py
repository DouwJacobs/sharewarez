"""One inclusion policy for cached archives, live archives and direct shortcuts."""
import os
from pathlib import Path
import stat
from typing import TypedDict

from sharewarez.metadata_files import is_local_metadata_filename


class SourceEntry(TypedDict):
    relative_path: str
    path: str
    size: int
    mtime_ns: int


def source_entries(source_path, excluded_folders) -> list[SourceEntry]:
    source = Path(source_path).resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Archive source is not a directory.')
    excluded = {name.lower() for name in excluded_folders}
    entries: list[SourceEntry] = []

    def fail(error):
        raise error

    for root, dirs, files in os.walk(source, followlinks=False, onerror=fail):
        root_path = Path(root)
        dirs[:] = sorted(name for name in dirs if name.lower() not in excluded and not (root_path / name).is_symlink())
        for name in sorted(files):
            path = root_path / name
            if is_local_metadata_filename(name) or path.is_symlink():
                continue
            resolved = path.resolve(strict=True)
            if source not in resolved.parents:
                raise ValueError('Archive entry escaped its source directory.')
            info = resolved.stat()
            if not stat.S_ISREG(info.st_mode):
                continue
            entries.append({'relative_path': resolved.relative_to(source).as_posix(), 'path': str(resolved),
                            'size': info.st_size, 'mtime_ns': info.st_mtime_ns})
    entries.sort(key=lambda item: item['relative_path'].encode('utf-8'))
    return entries


def direct_package_path(source_path, entries):
    """Retain the sole root file shortcut only when no nested payload is included."""
    significant = [entry for entry in entries if not entry['relative_path'].lower().endswith(('.nfo', '.sfv'))
                   and entry['relative_path'].lower() != 'file_id.diz']
    if len(significant) == 1 and '/' not in significant[0]['relative_path'] and not any('/' in entry['relative_path'] for entry in entries):
        return significant[0]['path']
    return str(source_path)
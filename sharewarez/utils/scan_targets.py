"""One authority for scan paths, eligible children and schedule options."""
from dataclasses import dataclass
import os
import stat

from flask import current_app

from sharewarez.utils.security import get_allowed_base_directories


SCAN_OPTIONS = (
    'remove_missing', 'download_missing_images', 'force_updates_extras_scan',
    'fetch_hltb', 'force_hltb_refetch',
)


class ScanTargetError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def within(path, root):
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def validate_scan_options(options):
    if not isinstance(options, dict):
        raise ValueError('options must be an object of boolean scan options')
    if any(key not in SCAN_OPTIONS or type(value) is not bool for key, value in options.items()):
        raise ValueError('options accepts only the five supported boolean scan options')
    return dict(options)


def legacy_scan_options(options):
    """Return safe values plus whether an old payload needs an admin warning."""
    if not isinstance(options, dict):
        return {}, True
    safe = {key: value for key, value in options.items() if key in SCAN_OPTIONS and type(value) is bool}
    return safe, len(safe) != len(options)


@dataclass(frozen=True)
class ScanTarget:
    path: str
    mode: str
    is_file: bool
    device: int
    inode: int

    def owns_stored_path(self, path):
        # Never resolve a relative historical path against today's working dir.
        if not isinstance(path, str) or not os.path.isabs(path) or '\x00' in path:
            return False
        stored = os.path.normpath(path)
        resolved = os.path.realpath(stored)
        if self.is_file:
            return stored == self.path and resolved == self.path
        return os.path.dirname(stored) == self.path and within(resolved, self.path)


def resolve_scan_target(path, mode='folders', *, extensions=(), active_root_only=False):
    """Resolve relative paths under the active root, and legacy absolute paths
    under configured storage roots. Validate again at execution, not just enqueue.
    """
    if not isinstance(mode, str) or mode not in {'folders', 'files'}:
        raise ScanTargetError('scan_mode must be folders or files')
    if not isinstance(path, str) or not path.strip() or '\x00' in path or len(path) > 4096:
        raise ScanTargetError('Enter a valid scan path. Use . for the configured root.')
    path = path.strip()
    base = current_app.config.get('BASE_FOLDER_WINDOWS' if os.name == 'nt' else 'BASE_FOLDER_POSIX')
    relative = not os.path.isabs(path)
    if (relative or active_root_only) and not base:
        raise ScanTargetError('Scan location is not configured.', 404)
    roots = [base] if relative or active_root_only else get_allowed_base_directories(current_app)
    roots = [os.path.realpath(root) for root in roots if root and os.path.isabs(root)]
    resolved = os.path.realpath(os.path.join(base, path) if relative else path)
    if not any(within(resolved, root) for root in roots):
        raise ScanTargetError('Access denied - path outside allowed scan directories', 403)
    try:
        info = os.stat(resolved)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ScanTargetError('Scan location is unavailable.', 404) from exc
    except OSError as exc:
        raise ScanTargetError('Scan location could not be read. Check storage permissions.', 403) from exc
    is_file = stat.S_ISREG(info.st_mode)
    is_dir = stat.S_ISDIR(info.st_mode)
    if not is_dir and not (is_file and mode == 'files'):
        raise ScanTargetError('Folders mode requires a directory; Files mode accepts a directory or supported file.')
    if is_file and os.path.splitext(resolved)[1][1:].lower() not in {ext.lower() for ext in extensions}:
        raise ScanTargetError('This file type is not enabled. Configure it in Scan Manager → File types.')
    if not os.access(resolved, os.R_OK | (os.X_OK if is_dir else 0)):
        raise ScanTargetError('Scan location could not be read. Check storage permissions.', 403)
    return ScanTarget(resolved, mode, is_file, info.st_dev, info.st_ino)


def enumerate_scan_target(target, extensions, insensitive_patterns, sensitive_patterns):
    """Return direct eligible candidates and a completeness flag. A failed
    child is skipped for import, but prevents destructive reconciliation.
    """
    from sharewarez.utils.gamenames import clean_game_name

    paths = [target.path] if target.is_file else [os.path.join(target.path, name) for name in sorted(os.listdir(target.path))]
    candidates = []
    complete = True
    extensions = {ext.lower() for ext in extensions}
    for path in paths:
        try:
            resolved = os.path.realpath(path)
            if not within(resolved, target.path if not target.is_file else os.path.dirname(target.path)):
                complete = False
                continue
            info = os.stat(path)
            is_dir = stat.S_ISDIR(info.st_mode)
            is_file = stat.S_ISREG(info.st_mode)
            if not os.access(path, os.R_OK | (os.X_OK if is_dir else 0)):
                complete = False
                continue
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1][1:].lower()
            if target.mode == 'folders' and is_dir:
                candidates.append({'name': clean_game_name(name, insensitive_patterns, sensitive_patterns), 'full_path': path})
            elif target.mode == 'files' and is_file and ext in extensions:
                candidates.append({'name': clean_game_name(os.path.splitext(name)[0], insensitive_patterns, sensitive_patterns), 'full_path': path, 'file_type': ext})
        except OSError:
            complete = False
    return candidates, complete


def validate_scan_candidate(target, path):
    if not target.owns_stored_path(path):
        raise ScanTargetError('A game path moved outside the selected scan target.')
    info = os.stat(path)
    eligible = stat.S_ISDIR(info.st_mode) if target.mode == 'folders' else stat.S_ISREG(info.st_mode)
    if not eligible:
        raise ScanTargetError('A game path changed type during the scan.')

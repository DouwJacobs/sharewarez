"""Stage packaged themes before replacing installed copies, with rollback."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def _installation_lock(root):
    # All web workers share this filesystem lock. Keep its inode stable.
    with (root / ".install.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def install_packaged_themes(source_root, target_root):
    source_root, target_root = Path(source_root), Path(target_root)
    default = source_root / "default_theme"
    if not default.is_dir():
        raise FileNotFoundError("Packaged default theme is missing")
    sources = {"default": default}
    bundled = source_root / "bundled_themes"
    if bundled.is_dir():
        sources.update({p.name: p for p in sorted(bundled.iterdir()) if p.is_dir() and p.name != "default"})
    target_root.mkdir(parents=True, exist_ok=True)
    with _installation_lock(target_root):
        staging = Path(tempfile.mkdtemp(prefix=".theme-install-", dir=target_root))
        cleanup = True
        try:
            (staging / "new").mkdir()
            (staging / "old").mkdir()
            (staging / "failed").mkdir()
            for name, source in sources.items():
                staged = staging / "new" / name
                shutil.copytree(source, staged)
                metadata = json.loads((staged / "theme.json").read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError(f"Invalid packaged theme metadata: {name}")
            replaced, published = [], []
            try:
                for name in sources:
                    target = target_root / name
                    if target.exists():
                        os.replace(target, staging / "old" / name)
                        replaced.append(name)
                    os.replace(staging / "new" / name, target)
                    published.append(name)
            except Exception:
                try:
                    for name in reversed(list(sources)):
                        if name in published:
                            os.replace(target_root / name, staging / "failed" / name)
                        if name in replaced:
                            os.replace(staging / "old" / name, target_root / name)
                except Exception as rollback_error:
                    # Never clean away the only remaining originals if rollback fails.
                    cleanup = False
                    raise RuntimeError(f"Theme rollback needs recovery from {staging}") from rollback_error
                raise
        finally:
            if cleanup:
                shutil.rmtree(staging)

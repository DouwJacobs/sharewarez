"""Application version loaded from the repository's authoritative VERSION file."""

from pathlib import Path
import re


VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def read_version() -> str:
    """Return the validated semantic version from VERSION."""
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Unable to read application version from {VERSION_FILE}") from exc

    if not SEMVER_PATTERN.fullmatch(version):
        raise RuntimeError(f"Invalid semantic version in {VERSION_FILE}: {version!r}")
    return version


__version__ = read_version()

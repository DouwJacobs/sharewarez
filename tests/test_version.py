from pathlib import Path

import pytest

from sharewarez import app_version
from sharewarez.version import SEMVER_PATTERN, VERSION_FILE, __version__, read_version


def test_application_version_comes_from_authoritative_file():
    expected = VERSION_FILE.read_text(encoding="utf-8").strip()

    assert app_version == expected
    assert __version__ == expected
    assert read_version() == expected
    assert SEMVER_PATTERN.fullmatch(expected)


@pytest.mark.parametrize(
    "version",
    ("1", "1.2", "01.2.3", "1.02.3", "1.2.03", "v1.2.3", "1.2.3.4"),
)
def test_invalid_semantic_versions_are_rejected(monkeypatch, tmp_path, version):
    version_file = tmp_path / "VERSION"
    version_file.write_text(version, encoding="utf-8")
    monkeypatch.setattr("sharewarez.version.VERSION_FILE", version_file)

    with pytest.raises(RuntimeError, match="Invalid semantic version"):
        read_version()


def test_dockerfile_exposes_oci_version_metadata():
    dockerfile = Path(__file__).resolve().parent.parent / "Dockerfile"
    contents = dockerfile.read_text(encoding="utf-8")

    assert "ARG APP_VERSION\n" in contents
    assert 'org.opencontainers.image.version="${APP_VERSION}"' in contents
    assert 'test "${APP_VERSION}" = "$(tr -d' in contents

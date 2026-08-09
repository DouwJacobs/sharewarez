#!/usr/bin/env python3
"""Inspect, validate, or bump the authoritative semantic version."""

from argparse import ArgumentParser
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def current_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"VERSION does not contain valid SemVer: {version!r}")
    return version


def assert_clean_version_file() -> None:
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", str(VERSION_FILE)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("VERSION has uncommitted changes")


def check(tag: str | None) -> str:
    version = current_version()
    if tag and tag.removeprefix("v") != version:
        raise ValueError(f"Git tag {tag!r} does not match VERSION {version!r}")
    return version


def bump(part: str) -> str:
    version = current_version()
    match = SEMVER_PATTERN.fullmatch(version)
    assert match is not None
    major, minor, patch = (int(value) for value in match.group(1, 2, 3))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    updated = f"{major}.{minor}.{patch}"
    VERSION_FILE.write_text(f"{updated}\n", encoding="utf-8")
    return updated


def main() -> int:
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("current")
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--tag")
    bump_parser = subparsers.add_parser("bump")
    bump_parser.add_argument("part", choices=("major", "minor", "patch"))
    args = parser.parse_args()

    try:
        if args.command == "current":
            print(current_version())
        elif args.command == "check":
            print(check(args.tag))
        else:
            assert_clean_version_file()
            print(bump(args.part))
    except (OSError, ValueError) as exc:
        print(f"version error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

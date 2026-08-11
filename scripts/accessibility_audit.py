#!/usr/bin/env python3
"""Fail when templates violate baseline automated accessibility contracts."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re

from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_ROOT = ROOT / "sharewarez" / "templates"
NAME_ATTRIBUTES = ("aria-label", "aria-labelledby", "title")


def _has_accessible_name(element: Tag) -> bool:
    if any(str(element.get(attribute, "")).strip() for attribute in NAME_ATTRIBUTES):
        return True
    if element.get_text(" ", strip=True):
        return True
    return any(str(image.get("alt", "")).strip() for image in element.find_all("img"))


def audit_template(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"\{#.*?#\}", "", source, flags=re.DOTALL)
    soup = BeautifulSoup(source, "html.parser")
    issues: list[str] = []

    html = soup.find("html")
    if html is not None and not str(html.get("lang", "")).strip():
        issues.append("document root is missing a lang attribute")

    for image in soup.find_all("img"):
        if not image.has_attr("alt"):
            issues.append(f"image is missing alt text: {image.get('class') or image.get('id') or image.get('src')}")

    for frame in soup.find_all("iframe"):
        if not str(frame.get("title", "")).strip():
            issues.append(f"iframe is missing a title: {frame.get('class') or frame.get('src')}")

    for element in soup.find_all(["button", "a"]):
        if element.name == "a" and not element.has_attr("href"):
            continue
        if not _has_accessible_name(element):
            issues.append(f"{element.name} is missing an accessible name: {element.get('id') or element.get('class')}")

    labels = {str(label.get("for")) for label in soup.find_all("label") if label.get("for")}
    for control in soup.find_all(["input", "select", "textarea"]):
        if control.name == "input" and str(control.get("type", "text")).lower() in {
            "hidden", "submit", "reset", "button", "image",
        }:
            continue
        control_id = str(control.get("id", ""))
        named = (
            any(str(control.get(attribute, "")).strip() for attribute in NAME_ATTRIBUTES)
            or control_id in labels
            or control.find_parent("label") is not None
        )
        if not named:
            issues.append(f"form control is missing a label: {control_id or control.get('name') or control.name}")

    for dialog in soup.find_all(attrs={"role": ["dialog", "alertdialog"]}):
        if not (dialog.get("aria-label") or dialog.get("aria-labelledby")):
            issues.append(f"dialog is missing an accessible name: {dialog.get('id') or dialog.get('class')}")
        if dialog.get("role") == "dialog" and dialog.get("aria-modal") != "true":
            issues.append(f"dialog is missing aria-modal=true: {dialog.get('id') or dialog.get('class')}")

    literal_ids = [str(tag["id"]) for tag in soup.find_all(attrs={"id": True}) if "{{" not in str(tag["id"])]
    for duplicate, count in Counter(literal_ids).items():
        if count > 1:
            issues.append(f"duplicate static id '{duplicate}' appears {count} times")

    return issues


def audit_templates(template_root: Path = DEFAULT_TEMPLATE_ROOT) -> dict[Path, list[str]]:
    return {
        path: issues
        for path in sorted(template_root.rglob("*.html"))
        if (issues := audit_template(path))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_root", nargs="?", type=Path, default=DEFAULT_TEMPLATE_ROOT)
    args = parser.parse_args()
    failures = audit_templates(args.template_root)
    if not failures:
        print(f"Accessibility audit passed for {len(list(args.template_root.rglob('*.html')))} templates")
        return 0

    for path, issues in failures.items():
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        for issue in issues:
            print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

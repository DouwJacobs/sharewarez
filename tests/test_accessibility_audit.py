import subprocess
import sys
from pathlib import Path

import pytest

from scripts.accessibility_audit import audit_template


ROOT = Path(__file__).resolve().parents[1]


def test_all_templates_pass_accessibility_audit():
    result = subprocess.run(
        [sys.executable, "scripts/accessibility_audit.py"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("markup", "expected_issue"),
    [
        ('<html><body></body></html>', "missing a lang attribute"),
        ('<img src="cover.jpg">', "image is missing alt text"),
        ('<iframe src="video"></iframe>', "iframe is missing a title"),
        ('<button><i class="icon"></i></button>', "button is missing an accessible name"),
        ('<input id="search">', "form control is missing a label"),
        ('<div role="dialog" aria-label="Example"></div>', "missing aria-modal=true"),
        ('<div id="repeat"></div><div id="repeat"></div>', "duplicate static id"),
    ],
)
def test_accessibility_audit_rejects_invalid_markup(tmp_path, markup, expected_issue):
    template = tmp_path / "invalid.html"
    template.write_text(markup, encoding="utf-8")

    assert any(expected_issue in issue for issue in audit_template(template))

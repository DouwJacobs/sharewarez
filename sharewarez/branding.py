"""Shared product-brand defaults.

Runtime settings may override these display values. Compatibility identifiers
such as package names, environment variables, and webhook headers deliberately
remain separate from the user-facing brand.
"""

from collections.abc import Mapping


DEFAULT_SITE_TITLE = "Game Library"
DEFAULT_BRAND_LOGO = "newstyle/sharewarez_logo.png"


def resolve_site_title(settings: Mapping[str, object] | None = None) -> str:
    """Return the configured display title or the product default."""
    configured = str((settings or {}).get("siteTitle") or "").strip()
    return configured or DEFAULT_SITE_TITLE

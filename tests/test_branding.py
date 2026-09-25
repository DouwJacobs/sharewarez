from sharewarez.branding import DEFAULT_BRAND_LOGO, DEFAULT_SITE_TITLE, resolve_site_title


def test_brand_defaults_and_configured_title_resolution():
    assert DEFAULT_SITE_TITLE == "Game Library"
    assert DEFAULT_BRAND_LOGO == "newstyle/sharewarez_logo.png"
    assert resolve_site_title() == DEFAULT_SITE_TITLE
    assert resolve_site_title({"siteTitle": "  "}) == DEFAULT_SITE_TITLE
    assert resolve_site_title({"siteTitle": "Arcade Shelf"}) == "Arcade Shelf"

DEFAULT_LIBRARY_PAGE_SIZE = 20
MAX_LIBRARY_PAGE_SIZE = 100


def normalize_library_pagination(page, per_page):
    """Return safe, bounded pagination values for game-library endpoints."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = DEFAULT_LIBRARY_PAGE_SIZE
    return max(1, page), min(MAX_LIBRARY_PAGE_SIZE, max(1, per_page))

import pytest

from sharewarez.utils.pagination import MAX_LIBRARY_PAGE_SIZE, normalize_library_pagination


@pytest.mark.parametrize(
    ('page', 'per_page', 'expected'),
    [
        (1, 20, (1, 20)),
        (0, 0, (1, 1)),
        (-5, -10, (1, 1)),
        ('2', '50', (2, 50)),
        ('invalid', 'invalid', (1, 20)),
        (1, 1000, (1, MAX_LIBRARY_PAGE_SIZE)),
    ],
)
def test_normalize_library_pagination(page, per_page, expected):
    assert normalize_library_pagination(page, per_page) == expected

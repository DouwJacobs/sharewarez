"""Product-prefixed environment variables with legacy-name compatibility."""

import os


CURRENT_PREFIX = 'GAMELIBRARY'
LEGACY_PREFIX = 'SHAREWAREZ'


def get_product_env(suffix: str, default: str | None = None) -> str | None:
    """Read a product variable, preferring the current prefix when both exist."""
    current_name = f'{CURRENT_PREFIX}_{suffix}'
    if current_name in os.environ:
        return os.environ[current_name]
    return os.getenv(f'{LEGACY_PREFIX}_{suffix}', default)


def product_env_enabled(suffix: str, default: bool = False) -> bool:
    """Read a product variable as a case-insensitive boolean."""
    fallback = 'true' if default else 'false'
    value = get_product_env(suffix, fallback)
    return value is not None and value.lower() == 'true'


def set_product_env(suffix: str, value: str) -> None:
    """Set both names while downstream processes transition to the new prefix."""
    os.environ[f'{CURRENT_PREFIX}_{suffix}'] = value
    os.environ[f'{LEGACY_PREFIX}_{suffix}'] = value

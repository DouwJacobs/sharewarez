"""Provider-neutral metadata discovery and fallback selection."""

from dataclasses import dataclass
import logging
from typing import Mapping, Protocol, Sequence


DEFAULT_METADATA_PROVIDER_ORDER = ('igdb',)
logger = logging.getLogger(__name__)


class MetadataSearchProvider(Protocol):
    """Normalized game-search boundary implemented by metadata providers."""

    name: str

    def search_games(self, term: str) -> tuple[list[dict], str | None]:
        """Return normalized game results and an optional user-safe error."""


@dataclass(frozen=True)
class MetadataSearchOutcome:
    results: list[dict]
    provider: str | None
    errors: tuple[str, ...] = ()

    @property
    def error(self) -> str | None:
        return '; '.join(self.errors) if self.errors else None


def normalize_provider_order(
    configured_order: Sequence[str] | None,
    available_providers: Sequence[str],
) -> tuple[str, ...]:
    """Return a stable, unique order containing only available providers."""
    available = {str(name).strip().lower() for name in available_providers}
    requested = configured_order or DEFAULT_METADATA_PROVIDER_ORDER
    normalized = []
    for value in requested:
        name = str(value).strip().lower()
        if name in available and name not in normalized:
            normalized.append(name)
    for name in DEFAULT_METADATA_PROVIDER_ORDER:
        if name in available and name not in normalized:
            normalized.append(name)
    for name in available_providers:
        normalized_name = str(name).strip().lower()
        if normalized_name in available and normalized_name not in normalized:
            normalized.append(normalized_name)
    return tuple(normalized)


def search_metadata_games(
    term: str,
    providers: Mapping[str, MetadataSearchProvider],
    configured_order: Sequence[str] | None = None,
) -> MetadataSearchOutcome:
    """Search providers in order until one returns results.

    Empty successful responses and provider failures both advance to the next
    provider. Errors are returned only when no provider produces a result.
    """
    provider_map = {
        str(name).strip().lower(): provider
        for name, provider in providers.items()
    }
    order = normalize_provider_order(configured_order, tuple(provider_map))
    errors = []

    for name in order:
        provider = provider_map[name]
        try:
            results, error = provider.search_games(term)
        except Exception:  # Providers must not prevent later fallbacks.
            logger.exception('Metadata provider %s failed during game search', name)
            errors.append(f'{name.upper()}: provider request failed')
            continue
        if results:
            return MetadataSearchOutcome(results=results, provider=name)
        if error:
            errors.append(f'{name.upper()}: {error}')

    return MetadataSearchOutcome(results=[], provider=None, errors=tuple(errors))

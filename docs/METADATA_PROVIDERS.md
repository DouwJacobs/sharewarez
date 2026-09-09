# Metadata providers

Sharewarez separates normalized metadata discovery from provider transport.
`sharewarez.utils.metadata_providers` owns ordered provider selection and failure
fallback. Each adapter returns the discovery fields consumed by Sharewarez rather
than exposing its remote response schema to callers.

The first adapter is `IGDBMetadataProvider`. It uses IGDB's documented API through
the existing authenticated, rate-limited request client. Website HTML and presskit
pages are not metadata sources and must not be scraped.

Game requests now consume the adapter for search, exact-game verification, and
edition discovery. The existing public helper names remain available while other
IGDB-specific refresh paths are migrated incrementally.

Provider ordering is normalized by `normalize_provider_order`. A failed or empty
provider advances to the next configured adapter; a successful non-empty result
ends the search. Errors returned to the caller name the failed provider but do not
include exception or credential details.

## Remaining work

The roadmap item remains open until a second API-backed provider exists, operators
can configure provider order, external identities are stored without assuming an
IGDB ID, and scalar/media refresh paths use normalized provider operations.

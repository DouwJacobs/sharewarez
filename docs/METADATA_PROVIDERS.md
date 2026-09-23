# Metadata providers

Sharewarez separates normalized metadata discovery from provider transport.
`sharewarez.utils.metadata_providers` owns ordered provider selection and failure
fallback. Each adapter returns the discovery fields consumed by Sharewarez rather
than exposing its remote response schema to callers.

The default adapter is `IGDBMetadataProvider`. It uses IGDB's documented API through
the existing authenticated, rate-limited request client. Website HTML and presskit
pages are not metadata sources and must not be scraped.

Game requests consume the adapter for search, exact-game verification, and edition
discovery. Image import and refresh use its normalized media operation, which
combines the game-linked artwork list with the direct IGDB artwork API so standalone
logo records are retained. Library scan discovery and scalar metadata refresh also
use adapter-owned full-game queries. Image-record repair, website discovery, and
involved-company lookup use the adapter as well. Existing public helper names remain
available as compatibility wrappers.

Provider ordering is normalized by `normalize_provider_order`. A failed or empty
provider advances to the next configured adapter; a successful non-empty result
ends the search. Errors returned to the caller name the failed provider but do not
include exception or credential details.

## Configure providers

Open **Administration → Integrations → Metadata**. IGDB remains the only enabled
provider after upgrade. To add RAWG, obtain an API key from RAWG, save it, explicitly
enable RAWG, and choose either IGDB-first or RAWG-first ordering. Saving a key does
not enable the provider. Connection tests are read-only and never import games.

RAWG access uses only `https://api.rawg.io/api`; Sharewarez does not scrape provider
websites. RAWG-derived discovery and request records keep the provider's source URL
and attribution. Automated tests use injected transports and never require a live
credential.

## Identity and compatibility

`game_external_identities` stores provider keys and string external IDs. One identity
per game is canonical and drives refresh. Legacy IGDB columns remain populated and
readable for IGDB so rolling upgrades do not lose data.

Local `sharewarez.json` files now use metadata version 2.0 with an `identity` object:

```json
{"metadata_version":"2.0","identity":{"provider":"rawg","external_id":"3498"}}
```

Version 1.0 files containing only `igdb_id` are still accepted. New IGDB files retain
that legacy key as well as the provider-neutral envelope.

Games created with **Custom game** receive a canonical `local` identity whose
external ID is the game's UUID. They no longer consume synthetic high-number IGDB
IDs. Editing and local-metadata writes preserve that local identity, while legacy
custom IDs remain readable during the compatibility window.

Provider failures and empty searches advance to the next enabled provider. Exact
refresh uses only the stored canonical identity and never assumes equal numeric IDs
belong to the same game. Missing optional capabilities cannot erase existing media.

# Metadata-provider completion and release plan

Prepared: 22 September 2026. Repository: WSL `/home/douw/sharewarez`.

## Outcome

Ship the already-committed 1.14.2 UI and IGDB adapter work, then complete the
metadata-provider roadmap item in a separate minor release. Completion means
operators can configure an ordered list of API-backed providers, the database no
longer assumes every external game identity is an IGDB integer, RAWG can act as a
real fallback to IGDB, and discovery/import/refresh behavior is covered by
database, route, adapter, fallback, migration, and rendered UI verification.

The implementation remains API-only. Provider websites must not be scraped.

## Release boundary

### Phase 0 — finish release 1.14.2

1. Preserve the current clean `main` branch and its 11 commits ahead of
   `origin/main`.
2. Run the complete local quality gate with its PostgreSQL and container-build
   stages enabled.
3. Smoke the exact image using the documented non-root, read-only, two-container
   topology and confirm `/health/ready`, web service, and job worker health.
4. Publish immutable `douwjacobs/gamelibrary:1.14.2` and update `latest`; verify
   both remote OCI manifests and record their digest.
5. Create and push `v1.14.2`, then push `main`. Never overwrite a pre-existing
   semantic-version tag.
6. Update the local handoff's current-release line only after publication is
   verified.

The provider-neutral schema and RAWG integration start after this boundary and
will be released as 1.15.0, not folded into the already prepared 1.14.2 image.

## Domain design

### Canonical provider identity

Add a `game_external_identities` table with:

- `id`: internal primary key;
- `game_uuid`: cascading foreign key to `games.uuid`;
- `provider`: normalized lowercase provider key, initially `igdb` or `rawg`;
- `external_id`: non-empty string so providers are not constrained to integers;
- `canonical`: whether this is the identity used for provider-led refresh;
- `provider_url`: optional validated HTTPS attribution/source URL;
- created/updated timestamps;
- unique constraints on `(provider, external_id)` and
  `(game_uuid, provider)`; and
- a partial uniqueness rule ensuring one canonical identity per game.

The `Game.igdb_id` column remains readable during the compatibility window. The
migration backfills an `igdb` identity for every populated value. New code reads
through provider-neutral helpers and dual-writes the legacy field only for IGDB.
Dropping the legacy column is explicitly deferred to a later breaking migration.

### Request identity

Extend new-game requests with `metadata_provider`, `provider_game_id`, and
`provider_parent_id` string fields. Add a provider-neutral uniqueness rule for
active/new-game requests and backfill existing rows from `igdb_id` and
`parent_igdb_id`. Retain the old IGDB fields for compatibility and rollback.

Request and discovery payloads use these stable normalized keys:

- `provider` and `provider_game_id`;
- `provider_parent_id`;
- `game_name`, `parent_game_name`, and `edition_name`;
- `cover_url`, `summary`, `platforms`, and `first_release_date`;
- `provider_url` and `attribution` where required; and
- provider-specific raw payload only inside the adapter/import boundary, never
  in templates or public API responses.

### Adapter contract

Split the current search-only protocol into explicit capabilities:

- discovery: search and fetch one normalized game;
- import: fetch normalized scalar metadata;
- media: cover, screenshots, and artwork when supported;
- relationships/editions: optional provider capability; and
- diagnostics: configured state and a harmless connection test.

Callers must feature-detect optional capabilities. A provider that cannot supply
logos or edition graphs must not erase data previously supplied by another
provider.

## Configuration and secrets

1. Add encrypted `rawg_api_key` storage using the existing `EncryptedString`
   boundary and include it in credential rotation coverage.
2. Store `metadata_provider_order` as a validated JSON list in global settings.
   Reject unknown, duplicated, disabled, or malformed entries at the route
   boundary; service code still normalizes defensively.
3. Treat a provider as available only when its required credentials exist and it
   is enabled. The default for upgraded installations remains `['igdb']`.
4. Add RAWG configuration and connection testing to the Integrations workspace.
   Explain its API-key and attribution requirements and do not enable it by
   merely saving a key.
5. Redact credentials from logs, diagnostics, exports, exceptions, and rendered
   HTML. Extend key-rotation and backup/restore tests.

## Provider registry and ordered fallback

1. Introduce one registry that builds configured adapters from global settings.
   Routes, scans, refreshes, requests, and image jobs must consume this registry
   rather than constructing `IGDBMetadataProvider` directly.
2. Preserve deterministic order. Search advances on an empty result or a safe
   provider failure and stops on the first non-empty provider result.
3. Exact fetch/refresh starts with the game's canonical identity. It may use
   another linked identity only when an explicit cross-provider mapping exists;
   it must never assume equal numeric IDs refer to the same game.
4. Record provider name in logs and job metadata without secrets or raw response
   bodies. User-facing errors may name the provider but must not expose request
   URLs containing credentials.
5. Add bounded timeouts, retry/backoff for transient failures, rate limiting, and
   test-injected transports for both adapters.

## RAWG adapter

1. Use only `https://api.rawg.io/api` endpoints with the operator's API key.
2. Normalize search and detail results into the shared contract. Map dates,
   platforms, genres, developers, publishers, ratings, website, cover, and
   screenshots only where semantics match Sharewarez fields.
3. Preserve RAWG IDs as strings at the domain boundary.
4. Provide a stable RAWG source URL and attribution text for any stored/displayed
   RAWG-derived metadata or media. Game Details and request discovery results
   must expose the required active backlink without creating a new visual system.
5. Do not synthesize unsupported edition, relationship, logo, or artwork data.
   Capability absence must be explicit and tested.
6. Unit tests use recorded-shaped fixtures and a fake transport; the normal test
   suite must never call the live RAWG service.

## Workflow migration

### Game requests

1. Make search results and selection provider-neutral in routes, JavaScript, and
   templates.
2. Verify the selected provider identity server-side before creating or joining
   a request.
3. Deduplicate requests and installed games by `(provider, external_id)`.
4. Keep IGDB edition selection where IGDB supports it; show a clear base-game
   request path for providers without edition capability.
5. Preserve old IGDB request URLs as compatibility adapters until all internal
   callers use the provider-neutral endpoints.

### Library scanning and manual identification

1. Search providers in configured order for folder-name identification.
2. Persist the winning canonical identity and the provider attribution.
3. Upgrade local metadata files to a versioned provider-neutral envelope while
   still reading legacy `{ "igdb_id": ... }` files.
4. Replace synthetic high-number IGDB IDs for manual games with an explicit
   local/manual identity path.
5. Duplicate detection uses provider identities plus existing path safeguards.

### Refresh, media, and relationships

1. Route scalar refresh through the canonical provider adapter while preserving
   field ownership and candidate conflict behavior.
2. Route media refresh through provider capabilities. Never delete existing
   media solely because the selected provider lacks that media category.
3. Generalize stored image provenance so image IDs and download URLs name their
   provider; retain IGDB compatibility reads during migration.
4. Generalize relationship identity columns from `related_igdb_id` to provider
   plus string external ID, backfill IGDB rows, and preserve unresolved links.
5. Reconcile relationships to local games through the identity table.

## Administrator UI

1. Extend the existing Integrations page rather than adding a parallel settings
   destination.
2. Add a flat Metadata providers section with enablement, credential status,
   connection testing, and an ordered provider control.
3. Use the shared `.app-page`, `.app-page-header`, `.app-surface`, form, button,
   and tab contracts. Keep one primary save action per region.
4. Ensure keyboard ordering controls have explicit accessible names and a
   non-drag alternative. Preserve CSRF, focus, pending, success, failure, and
   retry behavior.
5. Verify desktop and 390 × 844 layouts in Default, Ember, and a high-luminance
   theme. Confirm one mobile gutter, 44 px touch controls, no nested cards, no
   document overflow, and visible focus/contrast.

## Migration and compatibility tests

Cover all of these paths against PostgreSQL:

- fresh schema creation followed by head stamping;
- upgrade from the current 1.14.2 head with populated IGDB games, relationships,
  images, requests, and local metadata fixtures;
- downgrade/upgrade round trip for the new revision;
- idempotent identity backfill and collision failure behavior;
- legacy IGDB reads and dual writes;
- provider-neutral request deduplication;
- credential encryption and offline key rotation; and
- public API/path redaction with provider identities present.

## Verification ladder

Run progressively after each coherent commit:

1. adapter and normalization unit tests;
2. registry, ordering, empty-result, timeout, and failure-fallback tests;
3. model and migration tests on PostgreSQL;
4. request, scanning, refresh, image, relationship, settings, security, and
   credential tests;
5. Ruff, focused Mypy, compile checks, accessibility audit, JavaScript checks,
   and `git diff --check`;
6. rendered browser verification for Integrations, Requests, Game Details, Game
   Edit, and image refresh at desktop/mobile widths and across three palettes;
7. complete `scripts/quality-gate.sh` with container build enabled; and
8. hardened image smoke test before publishing 1.15.0 and `latest`.

No live provider test may mutate library data. A live RAWG smoke is optional and
requires an operator-supplied key; automated acceptance uses deterministic fake
transports.

## Commit sequence

Keep commits independently reviewable:

1. `docs: plan provider-neutral metadata completion`
2. `feat: add provider-neutral game identities`
3. `feat: add metadata provider registry and configuration`
4. `feat: add RAWG metadata adapter`
5. `refactor: make game requests provider-neutral`
6. `refactor: route library metadata through provider registry`
7. `refactor: generalize media and relationship identities`
8. `feat: add metadata provider administration UI`
9. `docs: complete metadata provider operations guidance`
10. `chore: release version 1.15.0`

Each commit must leave the focused tests green. Do not bundle unrelated UI
cleanup or the separate per-event notification/webhook roadmap work.

## Definition of done

- 1.14.2 is quality-gated, smoke-tested, published, tagged, and pushed.
- The metadata-provider roadmap checkbox can be checked without qualification.
- IGDB remains the default and upgraded installations behave as before until an
  administrator explicitly enables RAWG.
- A real ordered fallback from IGDB to RAWG is proven with deterministic tests.
- No application workflow requires an IGDB-shaped identity internally.
- Existing IGDB data, requests, relationships, local metadata, and images survive
  upgrade without loss.
- RAWG attribution and credential-handling obligations are visible and enforced.
- UI and accessibility contracts pass rendered verification.
- The complete local quality gate and hardened container smoke pass for 1.15.0.
- Documentation, `AGENTS.md`, roadmap state, migration guidance, and release
  instructions match the shipped behavior.

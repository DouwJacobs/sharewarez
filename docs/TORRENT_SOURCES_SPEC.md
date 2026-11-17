# Magnet links, torrent files, and games without local files

Status: implemented and verified in the working tree.
Date: 16 November 2026.

## Confirmed product decisions

- Administrators can attach magnet links and uploaded `.torrent` files to games.
- Administrators can create a normal game without any files on mounted drives,
  manually choosing its destination library. Any library can contain these games.
- A game supports multiple labeled sources, including different versions or repacks.
- Only administrators create, edit, or remove sources; signed-in members can use them.
- Opening a magnet or downloading a torrent hands off to the member's own client.
  Sharewarez does not run, queue, monitor, seed, or complete torrent downloads.
- Public torrents only in this version.
- The specification was approved before implementation; the feature ships in 1.17.0.

## User journeys

### Add a game without local files

Extend Add game manually with a source choice: **Local files** or **Magnet / torrent**.
For Magnet / torrent, require a destination library, game name, and at least one
valid source. Keep the library selector visible and editable even when preselected
from the current library. No mount configuration, folder picker, placeholder file,
or disk path is required. If there are no libraries, link to Create library and
retain entered text where practical.

Reuse the existing metadata identification and Custom game options. Source names
can suggest a title but cannot silently choose a metadata identity. A custom game
works without an external metadata service; identification and artwork can be
added later. Save the game and initial sources together, then open Game Details.

Each source has a required label (for example, "Windows — version 1.2") and exactly
one input: a magnet link or a torrent file. Allow multiple source rows. Show errors
on the affected row, retain text after validation failures, and explicitly request
file reselection when the browser cannot retain an upload. Never save a partial
game because one source failed validation.

### Add sources to an existing game

Game Edit gains a flat **Magnet links & torrents** section with source rows and
Add source, Edit label, Replace source, and Remove actions. Local files and torrent
sources can coexist. Changing a source never overwrites the game's version,
edition, identity, library, or disk path. Label/version distinctions belong to the
source; existing game metadata retains its current meaning.

### Use a source

Game Details lists labels and source type. Magnets offer **Open magnet** and
**Copy magnet**; uploaded files offer **Download torrent**. Preserve the existing
**Download game** action only for usable local content. Multiple sources require
an explicit choice; do not launch a default torrent automatically.

Show "Opens in your torrent client" beside the actions. Copy feedback means the
copy succeeded; opening a handler does not imply a download started or finished.
If no magnet handler is available, the copy action remains usable. No seeder,
progress, speed, availability, or completion claims are made.

### Browse and manage

Use the existing shared game cards across Library and Favorites, and preserve
Discovery, search, tags, relationships, collections, artwork, and play status.
Add source badges and a URL-backed source filter: All, Local files, Magnet/torrent,
and Magnet/torrent only. Local files and Magnet/torrent filters overlap for games
with both; filters describe registered sources, not a real-time mount-health check.
Counts and pagination use the same database predicates as results.

Do not display torrent-only games as 0-byte downloads. Show "No local files" and,
when available, a separately labeled torrent payload size. Magnet size is unknown
unless supplied as unverified metadata; do not count it as occupied storage.

## Existing implementation and affected assumptions

`Game.full_disk_path` is already nullable. `Library` is an organizational record
with a platform and does not require a root mount. Reuse both; do not introduce a
second game catalog or a mandatory torrent-library type.

The database alone is insufficient:

- `forms.py:AddGameForm` currently requires a disk path.
- `routes_games_ext/add.py` requires allowed base directories, validates a path,
  and can write local metadata. It also blocks creation while scanning.
- `routes_games_ext/edit.py` validates paths and calculates folder size/reads NFOs.
- `routes_library.py:serialize_library_cards` probes local metadata and images.
- `routes_games_ext/details.py` and local artwork routes contain filesystem paths.
- `routes_downloads_ext/initiate.py`, `play.py`, API download handlers, and archive
  services assume local content.
- `utilities.py` remove-missing scans call `os.path.exists(game.full_disk_path)`
  and remove missing records. Null paths must never enter this branch.
- `utils/game_core.py` contains path/identity deduplication and both deletion paths.

Review the current working tree before implementation: scan lifecycle, game
editing, and game-core files already have unrelated changes. Integrate with their
final behavior without reverting that work.

## Data design

Add `GameTorrentSource` / `game_torrent_sources` with:

| Field | Contract |
| --- | --- |
| `id` | UUID primary key |
| `game_uuid` | Required indexed FK to `games.uuid`; cascade on game deletion |
| `kind` | Required constrained value `magnet` or `torrent` |
| `label` | Required trimmed text, 1–160 characters |
| `magnet_uri` | Text, only for magnet sources |
| `storage_key` | Server-generated opaque file key, only for uploaded torrents |
| `original_filename` | Sanitized display/download name; never a filesystem path |
| `info_hash_v1`, `info_hash_v2` | Normalized validated hashes; at least one required |
| `file_sha256`, `file_bytes` | Integrity digest and stored attachment size for uploads |
| `payload_bytes` | Nullable nonnegative advertised game-content size |
| `created_by` | Nullable user FK with SET NULL on account deletion |
| `created_at`, `updated_at` | UTC timestamps |
| `revision` | Integer used to reject stale edits/removals |

Database checks enforce kind/field consistency and size ranges. Add the sources
relationship to Game with deletion behavior consistent with existing models.
Keep `Game.size` as local-content bytes; source-only records use its existing zero
default internally, while the UI displays the absence of local content explicitly.

Do not persist a second source-mode flag on Game. Derive `has_local_source` from
a nonblank path and `has_torrent_sources` using an indexed EXISTS query. Actual
local accessibility is checked when serving files, not by probing every card.

Exact repeated submissions on one game are idempotent. Use a normalized magnet
fingerprint or upload SHA-256 with a per-game database uniqueness constraint to
cover concurrent duplicates. Matching info hashes with different tracker data
produce a warning and an explicit keep-separate/replace choice; do not silently
merge trackers or discard one input. A magnet and torrent for the same content may
coexist. Hash matches across games warn administrators rather than globally forbid
them. Preserve existing global metadata-identity uniqueness rules.

## Validation and protocol support

Implement bounded parsing in a focused source service, with no tracker requests,
peer connections, remote torrent-URL fetching, or automatic metadata resolution.
Use a reviewed parser dependency if it meets these requirements; pin it in the
project dependency lock. If none does, implement only the bounded metadata parser
needed here and cover malformed inputs thoroughly.

- Accept v1, v2, and hybrid torrents and their supported magnet identifiers.
  Validate structure and hash encodings, including v1 hex/base32 and v2 multihash.
  Reject unsupported identifiers with an actionable error.
- Magnets must use `magnet:` and contain a supported valid `xt`. Limit input to
  16 KiB, reject control characters and malformed encoding, preserve valid repeated
  tracker parameters, and escape all rendering. Labels never become HTML.
- Torrent uploads: `.torrent` extension, maximum 10 MiB, valid bounded bencoded
  dictionary with valid `info` data. Do not trust MIME or extension alone. Reject
  malformed lengths, duplicate keys, inconsistent structures, negative sizes,
  excessive nesting (>64), and excessive decoded items (>100,000). Bound declared
  lengths before allocation. Validate v1 pieces and v2 file-tree/piece-layer
  structure, and compute hashes from the original encoded info bytes.
- Store and return original validated file bytes; do not rewrite/re-encode them.
  Never extract embedded paths or execute torrent content. Reject traversal,
  absolute paths, drive prefixes, and invalid path components in file entries.
- Reject `private=1` and malformed private flags. Require an explicit admin
  affirmation that each new/replaced source is public and contains no personal
  tracker credentials. A magnet does not reveal the private flag, and the absence
  of that flag in a file cannot establish that tracker URLs contain no secrets.
  Explain this limitation in field help; do not claim automatic public verification.
  Do not alter tracker URLs to try to make a private torrent public.

Protocol references: [BEP 3](https://www.bittorrent.org/beps/bep_0003.html) defines
v1 metainfo and info hashing; [BEP 9](https://www.bittorrent.org/beps/bep_0009.html)
describes magnet metadata retrieval; [BEP 52](https://www.bittorrent.org/beps/bep_0052.html)
defines v2 and hybrid metainfo. These references inform validation, not a server
torrent-client implementation.

## Routes, authorization, and storage

Proposed authenticated application endpoints (final blueprint prefixes follow
existing conventions):

| Method / path | Behavior |
| --- | --- |
| GET `/games/<uuid>/torrent-sources` | Labels, types, sizes, action URLs; members |
| POST `/games/<uuid>/torrent-sources` | Add source; admin, multipart or JSON |
| PATCH `/games/<uuid>/torrent-sources/<id>` | Edit/replace with revision; admin |
| DELETE `/games/<uuid>/torrent-sources/<id>` | Remove with revision; admin |
| GET `/games/<uuid>/torrent-sources/<id>/magnet` | Authorized URI retrieval |
| GET `/games/<uuid>/torrent-sources/<id>/file` | Authorized original torrent download |

Game creation uses the existing add form with one atomic service operation for
game plus initial sources. Enforce login, existing account-access restrictions,
game visibility, parent/source ownership, and administrator permission server-side.
Cookie-authenticated mutations require CSRF protection. Unknown or inaccessible
records must not leak source content. Use 400 validation, 413 oversized upload,
409 duplicate/stale conflict, and standard application authentication errors.

Store torrent files in persistent application-private storage outside static,
mounted game roots, and the ZIP cache. Use random server-generated names. Stream
downloads with `application/x-bittorrent`, safe attachment filenames, `nosniff`,
and private/no-store cache headers. URI retrieval also uses no-store. Keep raw
magnets and tracker URLs out of list APIs, logs, notifications, analytics, and PWA
caches. Fetch magnet contents on intentional interaction; never redirect arbitrary
user input. Do not extend public/token APIs with source contents in this version.

Validate before persistence. Stage uploads privately, finalize with an atomic file
rename, then commit database references; compensate on failure. Cleanup must handle
crashes and unreferenced files after a grace period. On replacement, retain the old
file until the transaction succeeds. On removal, commit database deletion before
file cleanup and retry failed cleanup. Both existing game deletion paths and library
deletion must use this lifecycle. Include attachments and integrity checks in backup
and restore; missing attachments display unavailable and leave the game intact.

Torrent handoffs create no DownloadRequest, DownloadTransfer, archive, quota usage,
or increment of `times_downloaded`. Administrative audit events record actor, game,
source ID, and operation without raw source content.

## Local-file lifecycle and scanning

- Source-only creation and editing bypass all mount/path validation and disk I/O.
  They still perform ordinary identity, library, metadata, and source validation.
- Allow source-only creation during a scan once transaction/identity conflicts are
  handled; retain relevant existing safeguards for local imports.
- Guard null/blank paths in metadata reads/writes, NFO, artwork fallback, size
  calculation, play, downloads, maintenance, and exports. `check_existing_game_by_path`
  must return no match for a missing path, never query all null-path games.
- Direct local-download and play requests for source-only games return a controlled
  unavailable response without creating jobs or quotas. Missing mounted content
  also gets a controlled response; torrent actions remain available.
- Remove-missing scans skip pathless records. If a missing local game has torrent
  sources, preserve the game, path, metadata, favorites, and sources; report local
  content missing instead of deleting it. Do not clear paths on a transient outage.
  Preserve existing local-only deletion semantics, including current mount safeguards.
- When a scan finds a metadata identity already represented by a source-only game,
  report a candidate for **Attach local files to existing game**. Do not create a
  duplicate or silently attach by name. Admin confirmation validates the path and
  retains the game UUID, current library, sources, and member data. If the scan's
  destination library differs, show that explicitly and offer a separate move.
- Administrators can also attach a validated local path directly in Game Edit.
  Removing a local association keeps torrent sources. Removing the final torrent
  source from a pathless game requires an explicit choice to retain a catalog-only
  entry or delete the game. Never silently delete the game or any mounted content.
- Existing pathless records remain valid during migration and appear as catalog-only
  when they have no sources. Creating a new pathless entry through this feature
  requires at least one source.

## Implementation sequence

1. Add model/migration, bounded validation service, private attachment storage,
   transactional cleanup, and backup support. Migration does not rewrite games or
   change identity constraints. Refuse downgrade while source rows exist unless an
   operator explicitly follows a documented data-export/removal procedure.
2. Add shared source capabilities and path guards; repair remove-missing and identity
   conflict handling before exposing source-only creation.
3. Implement authorized source endpoints and atomic creation/edit integration in
   `forms.py`, `routes_games_ext/add.py`, and `routes_games_ext/edit.py`.
4. Extend identify/edit templates, details actions, shared cards and serializers,
   source filters, and metadata/local-path attachment conflict UI. Audit download
   and play handlers, public serializers, search, and PWA behavior.
5. Add regression coverage and operator/help documentation. Update `DOWNLOADS.md`,
   `BACKUP_RESTORE.md`, and `UI_AUDIT.md` with implemented behavior and evidence.

Use shared page rails, one surface per section, flat source rows, existing theme
tokens, external labels, accessible errors, and keyboard focus handling. Ordinary
controls retain 42 px desktop / 44 px mobile dimensions. Synchronize canonical
default-theme assets under `setup/default_theme` with the installed theme copy.
No new component system is required.

## Acceptance and verification

1. With no allowed mount configured, an admin creates a custom magnet-only game in
   the manually selected library; it appears in Library, Details, Favorites, search,
   and collections. Repeat with a valid torrent file and an identified game.
2. Add multiple labeled magnets/torrents to a local game; members can choose each
   source. Existing local download behavior and counters remain correct.
3. Creation with one invalid source saves neither the game nor any sources; retries
   and concurrent repeated submissions do not create duplicates or orphan files.
4. Members and unauthenticated users cannot mutate sources; unauthorized requests,
   mismatched game/source IDs, missing CSRF, and stale revisions fail safely.
5. Test v1, v2, hybrid, malformed, oversized, deeply nested, traversal, private,
   duplicate, and tracker-variation fixtures. Prove validation makes no network calls.
6. A remove-missing scan preserves source-only games and hybrid games with missing
   disks. Null-path helpers never touch the working directory or select another
   null-path game. Local-only regression tests retain their expected behavior.
7. Attach local files to a source-only record and verify the UUID, library, favorites,
   metadata, and sources survive. Cross-library identity conflicts remain explicit.
8. Source-only local-download/play requests create no archive/job/transfer. Source
   opening and torrent file delivery consume no game-download quota or completion
   count. Unknown torrent size does not inflate/deflate local storage statistics.
9. Exercise replacement rollback, cleanup retry, game/library deletion, backup and
   restore, and missing attachment recovery without deleting mounted game files.
10. Verify filter counts/pagination and shared cards across initial and AJAX views;
    confirm source secrets are absent from generic APIs, logs, and offline caches.
11. Browser-check admin/member journeys at desktop and 390 × 844, keyboard-only use,
    long labels, absent artwork, errors, empty lists, upload failure/reselection,
    pending requests, copy feedback, and multiple source choices. No horizontal
    overflow; focus returns predictably after editing/removal.
12. Run focused model/route/scan/download/backup regressions, then the repository's
    required quality and migration gates. Use synthetic torrents; no real torrent
    downloading is needed for acceptance.

## Implementation verification record

The implementation is present in the working tree. Acceptance evidence is grouped
below by the numbered criteria above. The full production quality gate passed,
including all test modules, migrations, dependency audit, static checks, Compose,
and the release-equivalent container build and package compilation.

| Criteria | Evidence |
| --- | --- |
| 1 | `test_torrent_game_integration.py` covers mount-free creation, custom and IGDB identities, selected library, Details, Favorites, search, and collections. Browser creation passed for both magnets and uploaded torrent files. |
| 2, 8 | Integration coverage verifies a local file remains downloadable with a torrent alternative, source handoffs create no download request, and source actions leave completion counts unchanged. Existing download-route regressions also pass. |
| 3 | Invalid second sources and oversized uploads save no game; submitted text survives. Entry UUID retries are idempotent. Concurrent uploads leave one source and one attachment; the losing transaction cleans its file. |
| 4 | Route tests cover anonymous/member restrictions, parent/source mismatches, CSRF, and stale revisions. |
| 5 | Parser tests cover v1, v2, hybrid trees and Merkle layers, malformed/deep/traversal/private data, normalized duplicates, tracker variants, and offline validation with socket creation forbidden. |
| 6, 7 | Integration tests verify scan preservation of pathless/hybrid records, unchanged local-only deletion, and explicit cross-library file attachment preserving UUID, library, metadata, favorites, and sources. Null/blank metadata paths never probe the filesystem. |
| 9 | Storage/route tests cover replacement rollback, orphan cleanup and retry, source/game deletion, corrupt/missing attachments, and backup integrity. The actual PostgreSQL round-trip script preserved four synthetic sources and verified the uploaded attachment. Library deletion uses the same game deletion lifecycle. |
| 10 | Source-filter tests verify overlapping local/torrent predicates, counts, and both initial/AJAX rendering; raw magnets are absent from generic card responses. Source routes are private/no-store; PWA caching excludes them. Shared Library/Favorites serialization batches source flags without loading source payloads. |
| 11 | `UI_AUDIT.md` records default-theme desktop/mobile creation, upload, label edits, multiple sources, replacement, member copying, filters, keyboard focus, inline error recovery, control sizes, and overflow checks. |
| 12 | Focused feature acceptance and audit regressions pass alongside the full production quality gate. Current totals, real IGDB/artwork verification, upgrade evidence, and container checks are recorded in `RELEASE_1.17.0.md`. |

## Deliberately deferred

Server torrent-client integration, private trackers, torrent generation from local
files, remote URL imports, automatic torrent searching, swarm-health checks, bulk
imports, member submissions, source-bearing public API access, and per-source user
ACLs are separate features. Source attachment to updates/extras is also deferred;
the first version attaches labeled sources to the game record.

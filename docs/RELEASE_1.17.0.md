# GameLibrary 1.17.0

## Public magnet and torrent sources

Administrators can create games without local files in any chosen library and
attach multiple labeled magnet links or uploaded public torrent files. Existing
local games can also have torrent alternatives. Members open sources in their
own clients; GameLibrary does not download or seed torrents on the server.

Library and Favorites show accessible source badges. A badge opens the sole
magnet directly, with copy feedback and a timeout; multiple magnets and file-only
sources open the game's source list. Source filters share their predicates with
counts, pagination, and initial/AJAX rendering.

The editor separates source fields, actions, and confirmations, preserves local
file associations unless explicitly detached, and explains which source edits
save immediately. Replacement updates the displayed source type and clears the
completed replacement inputs.

## Reliability and metadata fixes

- IGDB name and ID searches share enum/date/rating/video/company/classification
  mapping. Add completes metadata and relationship enrichment, including Save &
  refresh, while retaining explicit manual edits and intentional empty values.
- Artwork requests are persistent jobs with retries and stale-identity checks,
  processed independently of long scans and recoverable after worker restarts.
- Bounded scan cancellation, durable restarts, lifecycle history, and the newer
  download/accounting behavior from 1.16.4 are preserved. Source-only and hybrid
  games survive remove-missing scans appropriately.
- Concurrent source removals cannot bypass the final-source decision. Duplicate
  submissions are idempotent, attachment integrity is verified, and parsing also
  rejects file/directory path collisions.
- Backups coordinate source writes and cleanup, verify referenced attachments,
  and publish a completed dump only after its sidecar and manifest are durable.
  Failed or incomplete new backups cannot masquerade as historical backups.
  Restore uses a database transaction and retry-safe attachment writes.
- Updated dependency locks include fixed SoupSieve and multidict versions.
  Preview auto-login tooling is excluded from the release image.

## Upgrade and storage

Migration `20261117_36` follows `20261106_35`; the release retains the complete
revision-32 through revision-35 ancestry. An upgrade of an isolated copy of the
saved revision-35 library preserved all game and user records and transfer-history
fields. A second upgrade was clean. No shared/production database was restamped
or modified during verification.

Uploaded torrent files require private persistent storage outside game mounts,
public assets, and the download cache. Compose provides `/data/torrent-sources`
using the `torrent_sources` volume. Hosts configured to allow an entire filesystem
as a game root must narrow those roots first. Keep the database dump, JSON
manifest, and `.torrents.zip` together. Stop the application before a full database
restore; source-level coordination does not replace general restore maintenance.

Private trackers, server torrent clients, automatic torrent discovery, remote URL
imports, swarm-health checks, bulk imports, and per-source member access rules
remain outside this release's agreed scope.

## Verification

The full production quality gate passed: **2,257 Python tests across 152 isolated
PostgreSQL modules**, dependency locking and vulnerability audit, lint,
accessibility, focused typing, migration/version/Compose checks, and the
release-equivalent container build and compilation. All **25 JavaScript runner
checks** passed.

Additional checks already completed include a real PostgreSQL backup/restore
round trip preserving five sources and one checksum-verified uploaded torrent,
the revision-35 upgrade drill, and 25 JavaScript runner checks. The archived-source
candidate passed readiness as version 1.17.0 under UID/GID 10001, a read-only root,
dropped capabilities, and no-new-privileges. Its separate artwork worker processed
a persistent job, and 192 authenticated requests across cards, APIs, details, and
static assets returned HTTP 200 without ASGI executor errors.

An authenticated test against real IGDB also passed both lookup methods and
source-only Add with Save & refresh. It populated the title, description, date,
category, and rating, then downloaded nine artwork files through the persistent
worker.

Actual operating-system torrent-client launch remains a manual browser check:
the preview browser blocks external-protocol handoffs. No real torrent download
was used for verification. Publishing the image does not deploy it to production.

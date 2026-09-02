# Resumable archive cache specification

Status: implemented on `main`  
Target: next release after 1.11.6  
Scope: resumable delivery for games, updates, and extras whose source is a directory

## Outcome

Sharewarez will turn a directory into one stable, reusable ZIP in an application-managed
cache and deliver that file through the existing HTTP byte-range path. Administrators do
not create, name, move, or remove these ZIPs manually. Sharewarez builds, validates,
reuses, expires, and evicts them.

This closes the current gap:

- Existing single-file downloads remain immediate and resumable.
- Existing on-demand ZIP streams remain available as a compatibility fallback.
- Directory and multipart releases become resumable after a one-time preparation step.
- A web worker never performs ZIP generation. Preparation runs in the persistent job
  worker, so a slow disk or large release cannot block normal web requests.

The first implementation is deliberately an HTTP download cache, not a torrent client.
It provides restart tolerance from one Sharewarez server; it does not provide swarm
delivery, piece hashes, or repair corrupted local files.

## Product rules

1. A resumable response always represents immutable bytes for the lifetime of its cache
   entry.
2. The existing `/download_zip/<download_id>` URL remains valid. Existing bookmarks,
   download requests, API consumers, quotas, permissions, and audit history continue to
   work.
3. Direct files never enter the archive cache.
4. Only directories that currently use on-demand ZIP streaming enter the cache.
5. One source snapshot creates at most one archive, even when several users request it
   simultaneously.
6. Building an archive does not consume a user's transfer slot, bandwidth allowance, or
   monthly download quota. Delivery does.
7. Cache files are disposable operational data. They are excluded from application and
   database backups.
8. A cached archive is never served from a public static directory.
9. Failed cache preparation cannot make the underlying game unavailable. Depending on
   policy, the user can retry preparation or use the existing non-resumable stream.
10. Sharewarez must never claim that a new browser download can append to an arbitrary
    partial file. Only the browser or download manager knows what it retained locally.

## User experience

### Direct file

The current experience is unchanged. The game page redirects immediately to the stable
file response. The Downloads page labels the link **Resumable**.

### Directory or multipart release

1. The user selects **Download**.
2. If a matching ready archive exists, delivery begins immediately.
3. Otherwise Sharewarez creates or joins one preparation job and redirects to the
   Downloads page.
4. The row shows **Preparing resumable download**, file count, estimated size, progress,
   and queue position when available.
5. When ready, the row changes to **Ready · resumable** and exposes one primary
   **Download** action. The application may notify through the in-app notification
   center, but must not repeatedly send external notifications.
6. If the connection drops, the page explains: **Open your browser's Downloads panel
   and choose Resume.** The same Sharewarez download URL remains reusable until the
   download request expires.

Do not auto-start a download after a long background job. Browsers can block delayed
downloads, and an unexpected large response is poor behavior. Auto-start is allowed only
when the archive was already ready during the user's original click.

### Resume semantics

The server makes resume reliable by returning:

- `Accept-Ranges: bytes` on `HEAD`, `200`, and `206` responses;
- `206 Partial Content`, exact `Content-Range`, and exact `Content-Length` for one range;
- `416 Range Not Satisfiable` and `Content-Range: bytes */<size>` for invalid ranges;
- a strong, stable `ETag` derived from the completed archive SHA-256;
- `Last-Modified` from the immutable archive completion time;
- correct `If-Range` handling: serve `206` only when the validator matches, otherwise
  send the complete current representation with `200`;
- the same sanitized filename for every response belonging to that archive generation;
- `X-Accel-Buffering: no` and documented proxy timeout/buffering requirements.

`HEAD` performs authentication and ownership checks but does not acquire a transfer slot,
create a transfer attempt, or reserve quota. A ranged `GET` records `range_start`,
`range_end`, HTTP status, and `is_resumed` on the transfer attempt. Quota continues to
count bytes actually served, including resumed ranges.

The existing byte counter is not a client checkpoint. It must never be used to choose a
resume offset because a proxy may have accepted bytes the user's device did not retain.

### Failure states

- **Waiting:** another user already caused the same archive to be queued or built.
- **Preparing:** the worker is writing and validating the archive.
- **Ready:** stable range-capable delivery is available.
- **Preparation failed:** show a concise reason, **Retry preparation**, and, when policy
  permits, **Download without resume**.
- **Source changed:** the old ready archive remains immutable for current links; a new
  request gets a new source fingerprint and archive generation.
- **Cache unavailable/full:** no partial archive is exposed. The UI shows the preflight
  failure and the configured compatibility action.

## Cache modes and defaults

Add `archiveCacheMode` with three values:

- `off`: preserve today's on-demand ZIP behavior exactly;
- `prefer` (recommended/default): prepare a resumable archive; if storage preflight or a
  build fails, offer the existing on-demand stream explicitly;
- `require`: directory downloads are unavailable until a resumable archive can be built;
  never fall back to a non-resumable stream.

Additional settings:

| Setting | Default | Bounds | Meaning |
| --- | ---: | ---: | --- |
| `archiveCacheMaxGb` | 100 | 1–100000 | Maximum managed ready and partial bytes |
| `archiveCacheMinFreeGb` | 10 | 1–10000 | Free space preserved on the cache filesystem |
| `archiveCacheRetentionDays` | 7 | 1–365 | Evict unused, unpinned entries after this age |
| `archiveCacheBuildConcurrency` | 1 | 1–4 | Maximum simultaneous archive builds |
| `archiveCacheFallbackEnabled` | true | boolean | Show non-resumable fallback in `prefer` mode |

The first release always uses ZIP `STORED` entries with ZIP64 enabled. Game releases are
usually already compressed; recompression wastes CPU, increases preparation time, and
makes capacity estimates less predictable. Compression controls should not be exposed in
the first administration page.

Environment configuration owns only the storage location:

- `DOWNLOAD_CACHE_DIR=/cache/downloads` in the container;
- development default: an instance-local non-static cache directory;
- Compose default: a dedicated `download_cache` named volume;
- optional `DOWNLOAD_CACHE_VOLUME` permits an operator-selected named volume or bind
  mount without changing application paths.

The image creates `/cache/downloads` for UID/GID `10001:10001`. Startup checks that the
directory is present, writable, on a filesystem with sufficient free space, and is not
inside the static asset tree or any read-only game source. Failure degrades cache health
but does not fail application readiness in `off` or `prefer` mode. It fails readiness in
`require` mode.

## Source identity and immutability

The cache key is SHA-256 over a versioned canonical manifest containing:

- archive format version;
- normalized source identity;
- each included relative POSIX path in bytewise sorted order;
- entry type;
- file size;
- nanosecond modification time;
- the exclusion-policy version.

Absolute source paths must not appear in filenames, URLs, logs, or user-facing APIs. They
may remain in the administrator-only database record because the worker needs to rebuild
the archive and the current download model already stores source paths.

The manifest fingerprint is intentionally metadata-based so requesting a large game does
not hash every source byte before queuing. During the build, the worker records each
file's stat before and after reading. It discards the temporary ZIP and requeues once if
any entry changes. The final ZIP SHA-256 is calculated while writing and becomes its
strong ETag.

Ready archives are immutable. A changed source produces a new cache key instead of
overwriting the old archive. Existing unexpired download links may finish against their
original generation; new links use the new generation.

## Data model

Add `DownloadArchive`:

| Column | Purpose |
| --- | --- |
| `id` UUID PK | Non-sequential internal identity |
| `cache_key` string(64), unique/indexed | Versioned source-manifest fingerprint |
| `source_path` text | Administrator-only rebuild source |
| `display_name` string(512) | Sanitized download filename |
| `state` string(24), indexed | `queued`, `building`, `ready`, `failed`, `deleting` |
| `relative_path` text, nullable | Path beneath `DOWNLOAD_CACHE_DIR`; never absolute |
| `source_bytes`, `archive_bytes` bigint | Capacity and progress accounting |
| `file_count` integer | Manifest count |
| `bytes_written` bigint | Live build progress |
| `sha256` string(64), nullable | Completed archive digest and ETag source |
| `format_version` integer | Enables future deterministic format changes |
| `build_job_id` FK, nullable | Link to persistent job history |
| `failure_code`, `failure_message` | Safe actionable failure details |
| `created_at`, `updated_at`, `ready_at` | Lifecycle timestamps |
| `last_accessed_at`, indexed | LRU and retention input |
| `pinned` boolean | Administrator eviction override |

Add nullable fields without changing or removing existing columns:

- `DownloadRequest.archive_id` (`SET NULL`) and `delivery_kind` (`direct`,
  `cached_archive`, `live_archive`);
- `DownloadTransfer.archive_id` (`SET NULL`), `range_start`, `range_end`, `http_status`,
  and `is_resumed`.

Do not overload `DownloadRequest.status` with cache internals. Its existing values remain
compatible. A request awaiting an archive uses `processing`; archive state and progress
come from its related `DownloadArchive`. Deleting a cache entry sets request archive
references to null; it does not delete download links or source content.

Database constraints must enforce non-negative sizes/progress, allowed states, one cache
key, and a ready entry having a relative path, positive archive size, and SHA-256.

## Build pipeline

Register `download.archive.build` in the persistent job system and give it a human label.
Archive work uses a bounded archive executor inside the existing `sharewarez.job_worker`
process. This preserves the intentional two-container `app` + `db` topology and prevents
a large build from starving short default-queue jobs.

Build algorithm:

1. Resolve and validate the source beneath configured allowed game roots.
2. Generate the canonical manifest and atomically get-or-create the cache row. The unique
   cache key and a database row lock deduplicate concurrent requests.
3. Run capacity preflight using estimated ZIP overhead, the configured maximum, reserved
   bytes for other builds, and minimum filesystem free space.
4. Evict eligible LRU entries if necessary.
5. Write `<archive-id>.<job-id>.partial` in the cache directory. Never use the final name
   during a build.
6. Stream entries in canonical order using bounded buffers, ZIP `STORED`, ZIP64, and safe
   relative names. Reject symlinks and any path that resolves outside the source root.
7. Heartbeat after at most one second or 64 MiB, update `bytes_written`, and cooperate
   with cancellation.
8. Re-stat source entries. If changed, delete the partial and retry once with a new
   manifest.
9. Close and test the central directory, reopen the ZIP, validate every entry header and
   CRC, flush, and fsync.
10. Atomically rename to `<cache-key>.zip`, fsync the directory, and commit `ready`, size,
    digest, and timestamps in one database transaction.
11. Wake polling user pages through their normal status request. Create one deduplicated
    in-app notification for users with waiting requests.

Job retries must start from a new partial file. Startup reconciliation deletes abandoned
partials older than the stale-job threshold, marks missing ready files failed, imports no
unknown files, and safely requeues cache rows whose owning worker died.

## Delivery-path changes

Preserve `/download_zip/<id>` and perform work in this order:

1. Authenticate the session and resolve the user-owned request.
2. Validate expiry and source ownership/path rules.
3. Resolve direct file, ready cached archive, preparation state, or explicit live-stream
   fallback.
4. Return preparation/error responses without acquiring a transfer slot.
5. For `HEAD`, return representation headers without admission or accounting.
6. For `GET`, acquire the existing per-user queued slot.
7. Reserve quota for only the selected full or ranged response.
8. Stream, heartbeat, detect disconnect, and finish the transfer using the current
   lifecycle.

Never derive a filesystem path directly from a URL or cache ID. Load the user-owned
download request, follow its archive relation, resolve `relative_path` beneath the
configured cache root, and repeat the safe-path containment check.

The existing live ZIP function stays isolated behind an explicit delivery-kind/policy
branch. Direct file behavior and `/api/downloadrom/<uuid>` remain unchanged except for
shared `HEAD`, validator, and transfer metadata improvements where applicable.

## Eviction and cleanup

Cleanup runs at startup, every 15 minutes in the job worker, and when capacity preflight
needs space. It is serialized with a PostgreSQL advisory lock across workers.

An entry is never eligible while:

- it is queued, building, or deleting;
- it has an active `DownloadTransfer` lease;
- it is pinned;
- its temporary file belongs to a live job.

Normal eviction order is failed/abandoned partials, expired retention entries, then ready
entries ordered by `last_accessed_at` oldest first. Capacity cleanup may evict a ready
archive still referenced by an unexpired download link; the link remains valid and
prepares or joins the archive again on its next use.

Deletion is two-phase: atomically mark `deleting`, confirm no active lease, unlink the
exact resolved file, then delete the row or record failure. A crash between phases is
reconciled at startup. Bulk clearing is refused for active/building entries and reports
precise skipped counts.

## Dedicated administration page

Add `/admin/download-cache` under **Operations**, linked from the shared admin navigation, and
register it in the centralized administrator navigation/search registry.

Use the established Sharewarez structure: `.app-page.app-page--wide`, one
`.app-page-header`, and a small number of sibling `.app-surface` sections. Do not nest
card surfaces. Reuse theme variables, shared 42/44 px controls, status badges, buttons,
pagination, and internal overflow ownership.

The page contains:

1. **Health summary:** mode, cache path status (without exposing it outside admin), used
   versus maximum capacity, filesystem free space, ready bytes, reclaimable bytes,
   active builds, queued builds, failures, and reuse count.
2. **Policy:** mode, maximum size, minimum free space, retention, build concurrency, and
   fallback toggle. Validate in the API and show the effective environment-owned path as
   read-only.
3. **Build activity:** flat live rows with content name, state, file count, bytes written,
   progress, elapsed time, requesting-user count, and cancel/retry action.
4. **Cache entries:** paginated searchable/filterable inventory with content, state,
   source size, archive size, created/last used, active leases, pin state, failure summary,
   and actions: verify, retry, pin/unpin, or evict.
5. **Maintenance actions:** **Run cleanup** as secondary; **Clear unused cache** as danger
   with a confirmation containing entry and byte counts. There is no action that removes
   source game files.
6. **Operational help:** concise explanation of preparation, resume behavior, cache
   eviction, proxy requirements, and where to resume in common browsers.

Desktop uses a summary grid and one intentionally scrollable inventory table. At mobile
width the summary becomes two columns then one, policy fields stack, build rows become
single-column, action buttons retain 44 px targets, and only the inventory wrapper may
scroll horizontally. Every progress region has a text equivalent and `aria-live` updates
must be polite and throttled.

Poll one compact JSON status endpoint every three seconds while the page is visible and
use backoff after failures. Preserve the last successful state during transient errors.
All mutations are POST/DELETE, administrator-only, CSRF-protected, audited, and safe to
repeat.

Initial route/API contract:

| Method and route | Result |
| --- | --- |
| `GET /admin/download-cache` | Render the administration page |
| `GET /admin/download-cache/status` | Compact health, capacity, and active-build JSON |
| `POST /admin/download-cache/policy` | Validate and save database-owned policy |
| `POST /admin/download-cache/cleanup` | Enqueue one deduplicated cleanup job |
| `POST /admin/download-cache/entries/<id>/verify` | Enqueue integrity verification |
| `POST /admin/download-cache/entries/<id>/retry` | Retry a failed or missing build |
| `POST /admin/download-cache/entries/<id>/pin` | Set the explicit pin state |
| `DELETE /admin/download-cache/entries/<id>` | Evict one eligible entry |
| `DELETE /admin/download-cache/unused` | Evict eligible unpinned entries only |

HTML form submissions may return redirects with flash messages; polling and progressive
enhancement APIs return a consistent `{status, message, data}` envelope. Conflicts such
as an active lease return `409`, validation failures return `400`, missing records return
`404`, and capacity/unavailable conditions return `507` only before an HTTP download
response has started.

## User Downloads page changes

Preserve the current page and request history. Add:

- a `Resumable`, `Preparing`, or `Streaming · restart required` delivery badge;
- deterministic preparation progress and a textual state;
- a primary **Download** action only when ready;
- **Retry preparation** after failure;
- an explicit **Download without resume** fallback only when policy allows;
- browser-resume guidance after an interrupted resumable transfer;
- status polling only while one of the visible rows is preparing.

Do not display a server-generated **Resume from X%** button. A normal **Download** action
returns the same representation URL, while the browser's own Downloads panel or a
download manager supplies the correct `Range` offset.

## Security and privacy

- Keep the existing authentication, ownership, expiry, and allowed-path checks.
- Cache filenames are content hashes plus `.zip`; user-facing names exist only in
  `Content-Disposition`.
- Reject symlinks, sockets, devices, FIFOs, path traversal, duplicate archive names, and
  entries that change type during build.
- Do not serve cache files through Flask static routes, nginx aliases, or direct object
  paths.
- Redact absolute paths from user APIs and ordinary logs.
- Apply existing request IDs and structured logging to build, delivery, validation,
  fallback, and eviction events.
- Rate-limit manual retry, verify, cleanup, and eviction actions.
- Strong ETags reveal only a digest of the generated archive, never a source path or
  credential.

## Observability

Add structured events and metrics for:

- builds queued/started/completed/failed/cancelled and duration;
- bytes written, cache used/free/reclaimable, and capacity-preflight failures;
- cache hits, misses, joins, evictions, and avoided rebuild bytes;
- full versus ranged responses and successfully completed resumed attempts;
- disconnects, `416` responses, source-change retries, and fallback streams;
- stale partial/job reconciliation and cache health.

The instance health dashboard reports degraded cache health without marking the whole
application down in `off`/`prefer`; `require` treats an unusable cache as not ready.

## Compatibility and rollout

1. Add nullable tables/columns in one Alembic migration. Do not rewrite or invalidate
   existing `DownloadRequest` or `DownloadTransfer` rows.
2. Ship the cache volume, startup preflight, administration page, and `off` mode before
   routing downloads through it.
3. Deploy with `prefer`. If the volume is unavailable, existing live directory streaming
   remains usable and the administration page shows a degraded warning.
4. Canary archive preparation with administrator requests, including a multipart release
   larger than 4 GiB and a forced disconnect/resume.
5. Enable user preparation while retaining the explicit fallback.
6. Consider `require` only after capacity, proxy, and restart drills pass in production.

Rollback is application-safe: set mode to `off` and run the prior live-stream path.
Nullable schema and cache files may remain. Never require a database downgrade to restore
downloads.

## Acceptance tests

### Existing behavior

- All current download route, quota, concurrency, monitoring, expiry, API, and range tests
  pass unchanged.
- A direct file returns byte-for-byte identical `200`, `206`, and `416` results.
- Existing download IDs created before the migration remain usable.
- `off` mode produces the current on-demand ZIP behavior.

### Archive correctness and deduplication

- Single and concurrent requests for the same unchanged directory create one build and
  one final archive.
- The ZIP includes the same files/exclusions and names as the current live ZIP.
- ZIP64 and multipart releases larger than 4 GiB validate and extract successfully.
- Unicode, long, and colliding paths are handled safely and deterministically.
- Source mutation during build never publishes a mixed or corrupt archive.

### Resume

- `HEAD` returns size, validators, filename, and `Accept-Ranges` without quota/transfer
  records.
- Disconnect after N bytes, retry with `Range: bytes=N-`, and concatenate responses to
  exactly the original archive SHA-256.
- Matching `If-Range` returns `206`; stale/missing validators return the safe full `200`.
- Invalid and multi-range requests return the existing `416` contract.
- Reverse-proxy integration preserves `Range`, `If-Range`, `206`, streaming backpressure,
  and long-transfer timeouts.

### Lifecycle and failure safety

- App and worker restarts recover or discard partial builds without exposing them.
- Disk-full, read-only cache, vanished source, permission errors, and database errors leave
  direct downloads and allowed live fallback working.
- Cleanup never removes an active/pinned/building archive and respects max-size,
  min-free-space, and retention policy.
- Evicting a ready archive never deletes a download link or source file.
- Quota counts only delivered response bytes; building and `HEAD` count zero.
- Slow archive creation does not materially increase normal page or direct-download
  latency under load.

### UI and accessibility

- User and administrator states render for empty, queued, building, ready, failed, full,
  degraded, and partially filtered data.
- Keyboard access, labels, focus order, confirmations, polite live updates, reduced motion,
  and semantic status colors pass the accessibility audit.
- `/downloads` and `/admin/download-cache` are visually verified at 1440 × 1000 and
  390 × 844 in the default theme plus one light and one dark custom theme.
- The document has no horizontal overflow; only the cache inventory owns an internal
  scrollbar.

## Definition of done

The feature is complete only when a directory-backed multipart release can be prepared
once, survive an app/worker restart, resume after a forced connection loss, remain
manageable from the dedicated administration page, clean itself within configured limits,
fall back safely when configured, and pass the full local quality gate including the
container build and proxy-level smoke test.

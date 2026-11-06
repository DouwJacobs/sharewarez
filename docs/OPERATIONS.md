# Production operations

## Development theme reloads

When `GAMELIBRARY_HOT_RELOAD=true`, application startup synchronizes the authored
`sharewarez/setup/default_theme` tree into the served default-theme directory.
The legacy `SHAREWAREZ_HOT_RELOAD` name remains accepted; when both are present,
the `GAMELIBRARY_*` value takes precedence. The initialization and migration
completion flags follow the same compatibility rule.
The synchronizer compares file contents and writes only new or changed assets.
This prevents Uvicorn's watcher from repeatedly reloading on unchanged copied
files and interrupting application startup during development.

## Packaged theme refreshes

Every container startup merges the default theme and other themes bundled with
the current image into the persistent `static/library/themes` directory. A
newly pulled image therefore updates its packaged theme assets without enabling
`DEV_MODE`. Separately installed user theme directories are left untouched.

## Health endpoints

- `GET /health/live` confirms the web process can serve requests. It does not
  query PostgreSQL and is omitted from request logs to avoid noise.
- `GET /health/ready` confirms PostgreSQL is reachable. Docker Compose uses
  this endpoint before considering the combined application container healthy.

Both endpoints are intentionally public, return only status and application
version, and remain available during first-run setup.

## Request diagnostics

Every response includes `X-Request-ID` and `Server-Timing`. A valid caller
request ID (8–64 ASCII letters, numbers, underscores, or hyphens) is preserved;
otherwise GameLibrary generates one. Use the ID to correlate a browser error
with the structured `gamelibrary.request` log entry.

Request logs default to one JSON object per line with timestamp, level, method,
path, status, duration, client address, and request ID. Set `LOG_LEVEL` to a
standard Python level. `LOG_FORMAT=json` is the production default.

Do not log credentials, session cookies, authorization headers, password-reset
tokens, query strings, or request bodies. The access logger intentionally logs
only the URL path.

## Combined process lifecycle

The `app` container supervises both Uvicorn and the persistent background-job
processor after one successful initialization/migration pass. A normal Docker
stop is forwarded to both processes. If either process exits unexpectedly, its
sibling is stopped and the container exits so `restart: unless-stopped` recovers
the full application unit. Use `docker compose logs -f app` for both streams.

## Resumable download cache

Directory downloads are prepared by the background-job process in the private
`/cache/downloads` mount. Compose uses the `download_cache` named volume by
default; set `DOWNLOAD_CACHE_VOLUME` to another named volume or an absolute bind
mount when cache storage belongs on a larger filesystem. The application owns
this disposable cache and never modifies source game files.

Use **Administration → Download cache** to check mount health, set the maximum
cache size and free-space reserve, change retention, pin entries, retry failed
builds, cancel queued/running builds, or evict unused archives. Cancellation is
cooperative and normally takes effect within one second of active file copying;
the worker removes the partial file and never modifies source data. A persisted
cancellation remains cancelled across an app restart. Cleanup runs when the
worker starts, every 15 minutes, and before a build that needs capacity. Builder
concurrency is read when the job process starts, so restart the app container
after changing it.

Because the supported topology has one job-worker process, worker startup
immediately recovers every job left in `running` by the previous process. Jobs
with a persisted cancellation request become cancelled; other interrupted jobs
return to their queue according to the normal retry policy.

The cache does not need backup. After loss or eviction, members can retry their
download to prepare it again from source. A missing ready archive is invalidated
at worker startup instead of being served as a broken link.

Archive creation uses no compression and calculates the archive SHA-256 and
per-file CRC values during the single source-to-cache write. Finalization checks
the ZIP index and publishes the file atomically; it does not reread every cached
byte. Do not manually delete a `.partial` file while its build is running. Use
the administrator Cancel action so the worker closes and removes it safely.

## Scheduled library scans

Administrators manage recurring auto scans from the Auto Scan tab in
`/admin/scan_management`. Background Jobs shows a compact schedule summary and
remains the execution-history view. Each
schedule stores its target library, absolute container-visible folder path,
scan mode, recurrence, next run, and scan options. The first-run field and all
displayed schedule timestamps use UTC. Folder targets are accepted only when
they are readable and inside a configured allowed base directory.

The background-job processor checks for due schedules every 30 seconds and
enqueues the existing incremental `library.scan` task. If the filesystem
fingerprint has not changed, the scan completes as skipped. Pausing a schedule
does not cancel a scan that has already been queued; use the job controls for
that. Resuming an overdue schedule moves its next run forward by one interval.
Run now queues an immediate execution without changing the recurring next-run
time.

# Admin instance diagnostics

`/admin/new_server_info` is the single operator-facing instance health dashboard. It combines local database readiness, stale background-job detection, and safe configuration/test-state summaries for SMTP, Discord, and IGDB. It deliberately does not perform outbound network calls during page rendering and never displays integration secrets. Each integration card links to its existing configuration tab under `/admin/integrations`.

Download counts and transfer reporting remain on `/admin/statistics`; they are not duplicated in instance health.

The development launcher aborts immediately when initialization fails and only
exports completion flags after success. An initialization error must be resolved
before restarting; the launcher must not start partially initialized workers.
## Recoverable theme reset

Administrator theme reset stages every packaged theme under the installed-theme
root before replacing any live directory. A filesystem lock serializes resets
across web workers. Failed publication restores the previous directories; custom
themes are retained. The staging path uses the same filesystem as the target so
renames do not require copying during publication.

If both publication and rollback fail, the operation retains its
`.theme-install-*` directory and records the recovery path. Stop the app before
manual recovery and restore originals from that directory's `old/` subtree.
Do not delete the staging directory until installed themes have been verified.

Tests of theme reset use explicit `THEME_SOURCE_ROOT` and `THEME_INSTALL_ROOT`
paths beneath a temporary directory. These are fixture overrides; normal
operation resolves source and installed assets from the application root.

## Outbound webhook operations

Webhook delivery uses the default background-job queue and therefore depends on
the bundled job-worker process. Failed deliveries and sanitized response status
are visible under Integrations. Delivery history older than 30 days is removed by
the maintenance thread. Keep `ALLOW_PRIVATE_WEBHOOK_TARGETS=false` unless trusted
administrators intentionally need access to an internal automation endpoint; see
`docs/OUTBOUND_WEBHOOKS.md` for signing and target-validation details.

## Scan target and cleanup safety

Scan entry points share `sharewarez/utils/scan_targets.py`. Relative paths resolve
against the active operating system's configured scan root; `.` selects that root.
Legacy absolute paths must remain inside a configured game-storage root. Workers
validate again before fingerprinting. Folders mode accepts directories; Files
mode accepts a directory or one regular file with an enabled extension.

Remove missing games is restricted to the selected library and direct stored
paths under the selected target (or the exact selected file). Missing/relative
historical paths, nested records and other roots are retained. Files mode only
reconciles enabled file extensions. Folders mode conservatively retains records
with a file type or a supported-file suffix, because absent legacy paths do not
prove a directory's type.

No removals run after empty/incomplete enumeration, processing failure,
cancellation, unreadable traversal, a changed candidate list or changed target
identity. Scan detail records explain why removals were skipped. Root readability,
identity and cancellation are checked again before destructive reconciliation;
a permission/I/O failure inspecting a historical game never proves absence.

Schedules accept only the five boolean scan options: `remove_missing`,
`download_missing_images`, `force_updates_extras_scan`, `fetch_hltb`, and
`force_hltb_refetch`. Unsupported legacy options are discarded at dispatch with a
warning in System Logs. An unavailable due target queues no work, records a
warning, and is checked again at the next normal interval. A paused schedule can
still be edited while its storage is offline. This does not change the supported
single-worker, two-container topology.

## Durable scan lifecycle

Scan work and restarts execute only in the existing job worker. Each execution
attempt creates a new ScanJob detail linked to its BackgroundJob, and writes the
latest scan ID into a newly assigned job payload before processing. Previous
terminal details remain available. Legacy restarts preserve the stored path,
library, mode and known options; missing historical HLTB overrides default to
false. A row lock and replacement-job pointer deduplicate simultaneous restarts.

Scan details separate matched, unmatched and failed units. An unmatched result
counts as processed only after its database record exists. Partial work has
status Failed and outcome partial; cancelled and interrupted attempts also use
the existing Failed enum value with their distinct outcome. No enum expansion is
required. Migration 20261105_33 adds the nullable outcome/options/owner/replacement
fields and the unmatched counter while preserving historical rows.

Fingerprint persistence and queue completion share a locked transaction. A scan
must persist a successful terminal result before the queue can complete it;
errors and cancellation cannot save a new successful fingerprint. Explicit scans
and restart actions force execution. Recurring scans can skip unchanged trees
unless cleanup, missing images, forced supplemental work or forced HLTB refresh
requires execution. The ordinary fetch-HLTB option enriches discovered games and
does not by itself prevent an unchanged skip.

Both cancellation entry points address the same durable job. Parallel scans keep
only one submitted unit per configured thread (capped at eight); cancellation
stops new submissions and drains started work. A normal worker stop finalizes
cancellation. An abrupt stop leaves durable ownership for the next single worker
to recover immediately, preserving the interrupted attempt before retrying with a
fresh detail. Web startup never changes worker-owned scans. The two-container
production topology is unchanged.

Scan Manager exposes queued work, terminal outcomes, counters, reasons, and job
detail links. Clear finished and single-row history deletion retain queued,
running/stopping, pending-replacement and unmatched-referenced scan records.
Background job history and scan detail history are separate objects.

### Manual scan selections

List Games creates a compact, owner-bound selection and displays 50 candidates
per page. Identify uses the generation and relative filename; a new listing,
changed library/root, removed file or changed eligibility invalidates the old
selection. Return to Scan Management, choose the target and List Games again.
Listing does not test write permissions or write local metadata. Metadata writes
remain part of saving an identification when enabled.
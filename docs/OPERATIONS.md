# Production operations

## Development theme reloads

When `SHAREWAREZ_HOT_RELOAD=true`, application startup synchronizes the authored
`sharewarez/setup/default_theme` tree into the served default-theme directory.
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

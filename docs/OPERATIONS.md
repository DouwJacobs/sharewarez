# Production operations

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

# Architecture decisions

Transactional email content is rendered through `sharewarez.utils.email_templates`. Five built-in definitions provide safe defaults, while optional administrator overrides are stored in `system_email_templates`. Rendering uses a sandboxed Jinja environment with strict variable validation and a shared branded HTML shell. See `docs/EMAIL_TEMPLATES.md`.

## Frontend strategy

GameLibrary remains a Flask/Jinja server-rendered application for production.
Existing authentication, CSRF protection, permissions, forms, themes, and routes
remain authoritative. A full Vite/React rewrite would duplicate those systems
and introduce excessive regression risk before production readiness.

React may be introduced through Vite as isolated interactive surfaces when a
feature materially benefits from client-side state—for example a visual smart-
collection builder, live job monitoring, metadata conflict resolution, or a
highly dynamic search grid. Such islands must consume documented APIs, preserve
server authorization and CSRF controls, participate in theme tokens, and retain
usable server-rendered fallbacks where practical.

A full SPA is a future major-version decision requiring an explicit API,
authentication, accessibility, offline, deployment, and migration design.

## Download live updates (implementation in progress)

SSE will run directly under ASGI rather than occupying the serialized Flask WSGI
adapter for the lifetime of each connection. PostgreSQL remains the source of
truth; no Redis or additional container is required.

Revision `20260904_24` installs transaction-bound change triggers on transfers,
download requests, archives, and archive-build jobs. Signals contain only a topic
name, never filenames, filesystem paths, user IDs, or credentials. Unchanged rows
and unrelated jobs do not signal. Rollbacks do not produce notifications.

`sharewarez.live_events` supplies one dedicated autocommit LISTEN connection per
web process, isolated from request-pool connections. It reconnects after failure
and requests a fresh snapshot. A bounded notification ring, three-topic set,
single scheduled event-loop callback, and one dirty flag per client prevent
unbounded queues under load. Initial subscriptions always request a snapshot.
Default admission limits are 100 connections per process and four per user per
process (multiply by the number of web workers for the deployment ceiling).

The `/api/live/downloads` ASGI endpoint accepts `view=downloads|activity|cache`
and up to 100 visible row `ids`. The downloads view is always owner-only, including
for administrators; activity and cache require an administrator. Each snapshot
revalidates the signed session and account state/role. Cookie credentials are not
accepted in the URL. Cross-site origins and untrusted hosts are rejected.

Snapshots run in background threads with short-lived Flask contexts/database
sessions. Sends have a ten-second timeout; disconnects release admission slots.
Updates are coalesced to at most once per second, with a fresh authorized snapshot
at least every 16 seconds as heartbeat and recovery from missed notifications.
Every reconnect starts fresh rather than replaying historical events. Transfer
payloads are bounded to 1,000 rows and explicitly flag truncation. Archive summary
totals are SQL aggregates rather than loading the entire inventory into Python.

The admin active-transfer, member Downloads and cache inventory frontends consume
SSE with polling fallback. Cache inventory snapshots include build-job stages and
active-transfer counts; actions remain CSRF-protected server forms. Pagination is
stable, with an explicit refresh hint when the total inventory count changes.
Both SSE activity snapshots and
the existing admin polling endpoint now supply current speed (an eight-second
window), per-attempt average speed, and ETA when remaining size and current rate
are meaningful. A bounded process-local sample store avoids multiplying samples
for multiple viewers. Reconnecting to another web worker warms its own window;
an unknown initial rate is null, not invented as zero.

An independent maintenance thread in the existing job process retires stale
transfers and expires links every 15 seconds, including while scans and archive
builds run. Monitoring GET endpoints no longer perform cleanup writes. The
existing 60-second stale threshold remains unchanged. Run the job process in
development as well as the web server when testing this behavior.

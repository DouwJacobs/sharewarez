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

This foundation does not yet expose a browser endpoint. Authorization, snapshot
queries, send timeouts, worker maintenance, and frontend integration are subsequent
stages; the existing polling screens remain unchanged until those land.

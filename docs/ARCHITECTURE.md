# Architecture decisions

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

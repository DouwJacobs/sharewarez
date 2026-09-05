# HTTP security controls

GameLibrary applies a central response policy for content type sniffing, frame
embedding, referrers, browser capabilities, opener isolation, and content
security. HSTS is emitted only for requests Flask identifies as HTTPS.

The default content security policy remains compatible with the existing
server-rendered templates, including their inline scripts and styles. New code
should prefer external assets so those allowances can be removed incrementally.
Override `SECURITY_CSP` only after testing every page and theme.

## Reverse proxies and hosts

`TRUST_PROXY_COUNT` defaults to `0`. Increase it only when all traffic reaches
GameLibrary through exactly that many trusted proxies that replace forwarded
headers. An incorrect value lets clients spoof their address, scheme, or host.

Set `TRUSTED_HOSTS` to a comma-separated production allowlist when the public
hostname is stable. Include every hostname operators use, but not URL schemes
or paths.

## Rate limiting

The default policy is 300 requests per minute per client. Login is limited to
10 POSTs per minute; registration and password-reset requests to 5; confirmation
links to 20. Limits return HTTP 429.

`memory://` requires no extra service and is suitable for one host, but each web
application instance maintains independent counters. Multi-host deployments should configure
a Flask-Limiter-compatible shared `RATELIMIT_STORAGE_URI` and install its client
dependency in a reviewed dependency update.

## Session and diagnostic boundaries (2026-09-05)

Disabling an account rejects its subsequent authenticated Flask requests and
direct downloads as well as SSE snapshots. These paths resolve current database
state instead of trusting a previously issued cookie alone. Moving a game to
another library requires administrator permission. The folder browser resolves
symlinks and only permits locations contained by its configured root.

Request diagnostics record route patterns rather than literal token-bearing
paths; unmatched paths are represented by a fixed marker. Authentication forms
and SMTP protocol transcripts must never be dumped to stdout or stderr.
All maintained launchers disable Uvicorn's separate raw access log with
`--no-access-log`; the redacted application request logger is authoritative.
A custom launcher must preserve this flag to avoid recording recovery tokens in
raw request paths or query strings.
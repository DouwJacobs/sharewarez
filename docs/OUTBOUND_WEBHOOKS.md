# Outbound webhooks

Administrators manage generic endpoints under **Administration → Integrations →
Webhooks**. Each named endpoint has an encrypted URL, an encrypted signing secret,
an enabled state, and an explicit event subscription list. The secret is generated
on creation or rotation and shown once.

## Envelope and signature

Every request is JSON and includes `version`, `id`, `type`, `occurred_at`,
`source`, an optional resource `subject`, and `data` containing a title, concise
privacy-aware message, safe application URL, and non-sensitive metadata. Email
addresses, filesystem paths, credentials, usernames, and raw issue comments are
not included. Version 1 is stable; incompatible changes require a new version.

Headers include:

- `X-Sharewarez-Delivery`: unique delivery UUID
- `X-Sharewarez-Event`: canonical event key
- `X-Sharewarez-Timestamp`: Unix timestamp used for replay checks
- `X-Sharewarez-Signature`: `sha256=` plus the hexadecimal HMAC-SHA256 of
  `<timestamp>.<raw request body>` using the endpoint secret

Receivers should reject stale timestamps, calculate the HMAC over the unmodified
body, and compare signatures with a constant-time comparison.

## Delivery and security

Delivery is asynchronous. `2xx` succeeds; network failures, `408`, `425`, `429`,
and `5xx` retry up to five attempts through the persistent job queue. Other `4xx`
responses fail immediately. The request timeout is ten seconds, redirects are
disabled, payloads are capped at 64 KiB, and stored response excerpts are capped
at 2 KiB. Failed deliveries can be retried from Integrations. History is retained
for 30 days.

Targets must use HTTPS and resolve only to public addresses. Loopback, link-local,
private, multicast, and unresolved targets are rejected both when saved and when
delivered. A trusted self-hosted deployment may set
`ALLOW_PRIVATE_WEBHOOK_TARGETS=true` to allow internal HTTP or HTTPS services.
Treat that override as privileged network access.

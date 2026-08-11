# Scoped API tokens

Users create and revoke personal API tokens from **Profile → API tokens**. The
complete bearer token is returned once. The database stores only a short display
prefix and an HMAC-SHA-256 digest keyed by the application `SECRET_KEY`; raw
tokens must never be logged or persisted.

Tokens may expire after 30, 90, or 365 days, or remain valid until revoked. A
user may keep at most 20 non-revoked tokens. Revocation is immediate.

Available scopes are:

- `profile:read`: account identity
- `library:read`: games and library metadata
- `downloads:read`: the owner's download requests and transfer history

Protected endpoints use `require_api_scope()` from
`sharewarez/utils/api_tokens.py`. Clients send the credential as
`Authorization: Bearer <token>`. `/api/token-introspect` is an authentication
diagnostic and requires `profile:read`. The versioned endpoints, pagination,
filters, and compatibility contract are documented in `docs/PUBLIC_API.md`.

Preserve `SECRET_KEY` across upgrades because it is part of token verification.
Changing it invalidates every existing API token, in addition to its existing
session and credential-encryption consequences.

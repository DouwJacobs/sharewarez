# Public API

GameStack exposes a read-only, versioned JSON API at `/api/v1`. Authenticate
with a personal API token from **Profile → API tokens**:

```http
Authorization: Bearer gst_prefix.secret
Accept: application/json
```

Tokens are shown once, may be revoked at any time, and must include the scope
listed for an endpoint. API responses never expose game filesystem paths,
generated archive locations, token digests, or another user's downloads.

## Endpoints

| Method and path | Scope | Description |
| --- | --- | --- |
| `GET /api/v1/profile` | `profile:read` | Token owner's account identity |
| `GET /api/v1/libraries` | `library:read` | Libraries and their game counts |
| `GET /api/v1/games` | `library:read` | Paginated game catalogue |
| `GET /api/v1/games/{uuid}` | `library:read` | Detailed metadata, series, franchises, and related releases |
| `GET /api/v1/downloads` | `downloads:read` | Token owner's download history |

`GET /api/token-introspect` remains available as an unversioned token diagnostic
and requires `profile:read`.

## Pagination and filters

Game and download lists accept `page` (default `1`) and `per_page` (default
`25`, maximum `100`). A list response has this envelope:

```json
{
  "data": [],
  "pagination": {"page": 1, "per_page": 25, "total": 0, "pages": 0}
}
```

Games accept `library_uuid` and a case-insensitive name query in `q`. Downloads
accept an exact `status` filter.

## Examples

```bash
curl -H "Authorization: Bearer $GAMESTACK_TOKEN" \
  "https://games.example.com/api/v1/games?q=witcher&per_page=10"

curl -H "Authorization: Bearer $GAMESTACK_TOKEN" \
  "https://games.example.com/api/v1/downloads?status=available"
```

## Errors and compatibility

Errors use `{"error": "message"}`. Missing or invalid credentials return
`401`; a valid token missing the required scope returns `403`; invalid query
parameters return `400`; and unknown game UUIDs return `404`.

Breaking response or behavior changes require a new URL version. New optional
fields and new endpoints may be added to `v1`. Clients should ignore response
fields they do not recognize.

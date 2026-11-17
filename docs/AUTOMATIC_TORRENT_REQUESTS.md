# Automatic torrent request fulfilment

Administrators can enable request-only catalogue lookup in Application Settings →
Community → Automatic torrent fulfilment. Select a destination library and enter
up to five public Hydra-compatible JSON catalogue URLs, one per line. Use **Test
sources**, then save the category. Automation defaults to off.

In Users, edit an account and enable **Automatic torrent request fulfilment**.
Permission defaults to denied, including for existing accounts. Both the global
switch and the account permission are required. A permitted user joining a
pending request can trigger fulfilment for everyone following that request.

New-game submissions queue persistent background work. The standard job worker
must be running. Manual game additions, update requests, and issue reports do not
trigger lookup. Revocation, account suspension, withdrawal, or a manual request
resolution takes effect before the worker publishes its result.

The catalogue contract is `{ "name": "Public source", "downloads": [
{ "title": "Game title", "uris": ["magnet:?..."], "uploadDate": "...",
"fileSize": "..." }] }`. Size is descriptive; upload date can be used by the
optional release-selection policy below. Supported
links are validated public magnets and direct `.torrent` files. Other download
hosts are skipped. Schema reference: [Hydra validators](https://github.com/hydralauncher/hydra/blob/v2.1.7/src/main/events/helpers/validators.ts).

Catalogues are cached per process for 15 minutes, with five cached sources and a
20 MiB response limit per source. Connections use checked public IP addresses
with the original TLS hostname. Private network destinations, credentials in
URLs, excessive redirects, oversized responses, and verification HTML are
rejected. Browser verification cannot be completed by the worker; configure an
accessible public source instead.

Matching ignores case and punctuation and removes only explicit known release
suffixes. Sequels and editions retain their identity. Multiple distinct matching
releases remain ambiguous; upload date does not establish which game version is
newest. No match or unresolved ambiguity leaves the request pending for an administrator.

**Choose the most recent upload**, under Application Settings → Community,
optionally resolves multiple matching releases using the catalogue's upload date.
It defaults to off. When enabled, all matching releases must have valid dates and
one must have a uniquely latest timestamp. Missing/invalid dates or a tie for
latest retain the admin source selector. Timezone offsets are compared in UTC;
date-only or unzoned values are interpreted as UTC. The policy considers all
matches, including those beyond the ten-choice admin display limit. It never
loosens title/edition matching or bypasses user permission checks. Already pending
requests require **Retry source lookup** after changing the policy. The result
records when the most recent upload rule was used.

Ambiguous lookup results now retain up to ten matching releases in the durable
job result. Request details shows radio choices with release title, catalogue,
size, and upload date. Select a release and press **Use release & fulfil** to
queue validation and fulfilment. The server resolves the choice from the saved
job result, rejects stale choices, and rechecks the administrator's role/account,
request status, configured source, and global switch before applying it. Admin
selection does not require the requester's automatic-fulfilment permission.

On success, the worker atomically creates or reuses the provider-identified game,
attaches sources, fulfils the request, satisfies interested requester links, and
records notification work. Matching any-edition followers in the same provider
family are also satisfied. Artwork and metadata enrichment run as separate
durable jobs. Game payloads are not downloaded onto the server.

Request details show the lookup outcome and source attribution. The retry action
is available for pending requests after work ends, provided at least one active
requester still has permission. Return a manually reviewed request to Pending
before explicitly retrying automation. Partial catalogue outages block automatic selection until the complete lookup
can be assessed; explicit saved admin choices remain available. Request lookups
have their own queue consumer so library scans do not delay them. Transient
catalogue and remote torrent-file failures use the job
queue's bounded three-attempt backoff. Job details retain unexpected errors.

Migration `20261117_37` adds the denied-by-default account permission and separate
lookup status/message columns. Existing game-request statuses are unchanged.

## Verification

The isolated PostgreSQL regression run passed 186 tests across the new catalogue,
workflow, and admin coverage plus existing request, torrent integration,
settings, background-job, and notification suites. Subsequent checks passed the
31 catalogue cases (including edition markers inside version suffixes) and the
authorized-join submission integration case. Migration coverage verifies upgrade,
repeat upgrade, denied defaults for existing users, and downgrade in an isolated
schema. Five settings JavaScript tests, Ruff, the 98-template accessibility audit,
and `git diff --check` passed. Desktop/mobile admin interaction evidence is in
`UI_AUDIT.md`. Live fulfilment with the example HydraLinks source remains dependent
on that source returning accessible JSON rather than browser verification HTML.

## Manual JSON catalogue upload

Under **Application Settings > Community > Upload a catalogue**, choose a
Hydra-compatible `.json` file downloaded in your browser and press **Upload
catalogue**. Files are limited to 20 MiB and must contain at least one usable
magnet or public torrent-file entry. HTML challenge pages and malformed files
are rejected without replacing the saved snapshot.

One uploaded snapshot is supported. A successful upload saves immediately,
shows its source name, usable entry count, original filename and import time,
and replaces the previous snapshot. Other unsaved settings drafts are retained.
Upload a newer file yourself to refresh it. The most-recent-upload matching
policy continues to compare each release's `uploadDate`, not the import time.

Uploads and configured URL catalogues are combined for lookup. To use only the
uploaded catalogue, clear **Public catalogue URLs** and save settings. In
particular, remove any URL returning 403: incomplete remote results intentionally
block automatic selection even if an uploaded catalogue matches. **Test sources**
checks the uploaded snapshot as well as any entered URLs.

The existing global switch, destination library, per-user permission, conservative
matching and admin selection rules also apply to uploaded entries. An uploaded
catalogue alone satisfies the source prerequisite for enabling automation.
Removing the only catalogue while automation is enabled requires disabling
automation or first saving another URL. Existing library games are retained.

The raw snapshot is stored privately in PostgreSQL, so normal database backups
include it; no separate catalogue volume is needed. Only metadata is rendered in
settings. Imports are administrator-only and CSRF-protected, with bounded reads,
content integrity checks and stale-replacement protection. Replacing a snapshot
invalidates saved candidate choices and stops in-flight fulfilment using the old
snapshot. Migration `20261117_39` adds the snapshot table.

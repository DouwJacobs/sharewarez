# Release 1.18.0

## Automatic torrent requests

- Configure public Hydra-style JSON catalogue URLs under Admin Settings > Community.
- Enable automatic fulfilment, choose a destination library and grant permission
  to individual users. All three are required; permission starts disabled.
- Eligible new-game requests create a game with matching magnet/torrent sources
  and mark the request fulfilled. Metadata and artwork enrichment runs afterward.
- Optionally choose the most recent catalogue upload when several releases match.
  Missing, invalid or tied dates require admin selection. Upload date does not
  guarantee the latest game version.
- Admins can inspect matching candidates, select a release and retry lookup.
  Manual game additions do not trigger automatic lookup.

## Fixes and audit

- Separate request processing from slow library scans; improve retries,
  cancellation, legacy request handling and failure messages.
- Prevent selection from incomplete catalogue results and stale metadata updates.
- Keep original torrent attachments and existing requests across upgrades.
- Correct user-setting saves with blank About fields, search focus styling,
  release-card spacing and magnet icon alignment.
- Remove the homepage magnet handoff/copy prompt.
- Show explicit magnet clicks and torrent-file downloads in Admin Downloads.
  These record user actions, without claiming torrent-client progress.

## Faster validation

- Routine changes run affected regressions automatically, with conservative full
  fallback for shared or unknown production changes.
- Run test modules concurrently in separate disposable databases, reduce repeated
  fixture setup, and retain production password-policy coverage.
- Remove 28 brittle source-text assertions while retaining behavioural,
  permission, migration, JavaScript and accessibility checks.
- Reuse Docker dependency layers after version bumps; resolve locks only when needed.

## Verification

The full retained suite passed: 2,338 tests in 273.18 seconds, alongside lint,
static typing, JavaScript, accessibility, migration/version checks and a clean
dependency vulnerability audit. The audit baseline took 395.91 seconds.
Ordinary changes use affected selection rather than this full audit run.

An isolated read-only container upgraded from 1.17.0 to 1.18.0 and preserved
synthetic games, requests and torrent attachments. Authenticated smoke checks
covered default-denied permission, library/settings/history, CSRF user edits,
admin access controls, magnet/torrent action logging and the dedicated request
worker. No production deployment is performed by publishing this release.

See [the audit](RELEASE_AUDIT_1.18.0.md) and [validation guide](VALIDATION.md).

# Release 1.18.1

Administrators can now upload a Hydra-compatible catalogue JSON file under
**Application Settings > Community > Upload a catalogue**. This provides a manual
snapshot when a catalogue website blocks server requests with a browser challenge.

- Upload or replace one catalogue, up to 20 MiB; see its name, usable entry count,
  filename and import time. Uploads save immediately, preserving settings drafts.
- Use the uploaded snapshot alone or alongside public URL catalogues. Clear and
  save the URL list when you want to use only the uploaded file.
- Keep the existing automation switch, destination library, per-user permission,
  title matching and most-recent-release policy.
- Validate uploaded JSON and usable torrent/magnet entries before replacing the
  saved snapshot. Invalid files leave the existing catalogue intact.
- Protect upload/removal with administrator authorization, CSRF and stale-edit
  checks. A changed snapshot invalidates old candidate choices and in-flight work.
- Store the snapshot privately in PostgreSQL so ordinary database backups include
  it. Migration `20261117_39` adds the snapshot table.

The snapshot needs manual replacement when new releases are available. A blocked
URL still prevents automatic selection from incomplete inputs; remove that URL
from settings when using the uploaded snapshot instead.

Authenticated desktop/mobile browser checks covered real file upload, invalid
replacement, preserved settings drafts and responsive layout. Regression coverage
includes upload-only fulfilment, permissions, size bounds, stale selection,
replacement during lookup and reversible migration.

## Verification

Release validation passed 484 affected Python tests across 30 modules in 60.62
seconds, plus JavaScript regressions, accessibility, lint, focused type checks,
version/migration/Compose checks and a dependency audit with no known
vulnerabilities. The release image is built from the exact committed revision
and smoke-tested with a separate upgrade database before publication.

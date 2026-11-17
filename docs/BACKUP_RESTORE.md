# Backup and restore

GameLibrary creates PostgreSQL custom-format archives with SHA-256 manifests.
Every archive is validated with `pg_restore --list` before it is accepted.
Docker startup creates a pre-upgrade snapshot whenever the Alembic revision is
behind and retains the newest ten backups by default.

Backups are written to `BACKUP_HOST_PATH` (`./data/backups` by default). This
covers application data and configuration stored in PostgreSQL. Also back up
`LIBRARY_HOST_PATH` separately because it contains generated covers, themes,
and prepared ZIP files. The source game library mounted at `/storage` remains
the authoritative copy of game content and is not duplicated.

## Manual backup and validation

```bash
docker compose exec app python -m sharewarez.backups create --reason manual
docker compose exec app python -m sharewarez.backups verify /backups/FILE.dump
docker compose exec app python -m sharewarez.backups prune --retain 10
```

Copy both the `.dump` and matching `.json` manifest off the application host.
Periodically test restoration on a separate PostgreSQL instance.

## Restore

A restore replaces database objects and must be performed while the application
container is stopped. Keep PostgreSQL running:

```bash
docker compose stop app
docker compose run --rm --no-deps app \
  python -m sharewarez.backups restore /backups/FILE.dump --confirm sharewarez
docker compose up -d app
```

The confirmation must exactly match the target database name. Restore validates
the archive and checksum before invoking `pg_restore --clean --if-exists`.
Review container output and the `/admin/background-jobs` page after startup.

## Recovery drill

At least quarterly: create a manual backup, restore it into an isolated database,
run `flask db current`, sign in, browse the library, and execute a no-op or scan
job. Record the date and result outside the application host.
# Torrent attachment storage

`TORRENT_STORAGE_DIR` selects private persistent storage for uploaded `.torrent`
files. The default is `instance/torrent_sources`; Compose uses the dedicated
`torrent_sources` volume at `/data/torrent-sources`. All web and worker processes,
including backup commands, must use the same directory. Do not place it beneath
the public static folder, game mounts, or the download archive cache.

New database backups include a matching `.torrents.zip` attachment sidecar and
its SHA-256 digest in the existing JSON manifest. Keep all three files together.
Verification checks the sidecar and each attachment's checksum; restore verifies
and installs the private files before restoring database references. Backup
retention removes the matching sidecar along with its database dump. Historical
backups without the new manifest field remain supported.

Backup and restore automatically take an exclusive PostgreSQL advisory lock.
Source mutations, game deletion, and attachment maintenance take the matching
shared transaction lock, so database references and attachment files represent
the same point in time across web, worker, and command-line processes. Pending
source changes wait until the backup or restore finishes. All processes must use
the same application database and private storage directory; do not modify that
directory manually during a backup or restore. The sidecar contains only files
referenced by the database and checks each against its stored size and checksum.
Missing or corrupt referenced files fail the backup instead of producing an
incomplete recovery point. Mounted game content is not included.

New backups are built and verified in a private staging directory. The sidecar
and manifest are published first, and the final `.dump` appears only when both
are ready. Publication flushes files and directory entries to disk; a failed
backup does not leave a valid-looking database dump. Archives containing the
torrent-source table require their manifest and sidecar when verified or
restored. Historical archives from before that table still work without them.
Database restore runs in one transaction, so a restore error rolls back database
changes. Immutable attachment files installed before a failed restore are safe
unreferenced files and are eligible for normal maintenance cleanup.
Missing or corrupt attachments produce an unavailable response and preserve the
game record. Administrators can replace the affected source in Game Edit.

Do not configure `/` or an entire Windows drive as an allowed game folder:
there would be no private location outside that folder for torrent attachments.
For example, use `/storage` or `C:\Games` for game content and the default
`instance/torrent_sources` (or the separate Compose volume) for attachments.

Replaced and deleted attachment files remain eligible for safe retry cleanup.
The background worker removes unreferenced uploads after a 24-hour grace period,
checking every 15 minutes. This also cleans uploads orphaned by process crashes.
Source metadata cascades when games are deleted; cleanup never deletes mounted
game content. Database downgrade refuses to remove the feature while source
records remain: export the sources and attachments and explicitly remove the
records first if a downgrade is required.

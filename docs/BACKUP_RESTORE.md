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

# Container runtime security

GameLibrary application images run as the fixed unprivileged identity
`10001:10001`. Compose makes the combined web/background application root
filesystem read-only, drops all Linux capabilities, prevents privilege
escalation, and provides a size-limited temporary filesystem. Game storage
remains read-only.

## Existing deployment migration

Before starting an upgraded image, stop the application and grant
the container identity ownership of the two writable host directories:

```bash
docker compose stop app
mkdir -p ./data/library ./data/backups
sudo chown -R 10001:10001 ./data/library ./data/backups
docker compose up -d
docker compose ps
```

Substitute the configured `LIBRARY_HOST_PATH` and `BACKUP_HOST_PATH` when they
do not use the defaults. The game directory configured by `DATA_FOLDER_WAREZ`
does not need to be owned by this identity, but UID 10001 must have directory
traverse and file read permission.

Confirm the runtime identity and writable boundaries after migration:

```bash
docker compose exec app id
docker compose exec app test -w /app/sharewarez/static/library
docker compose exec app test -w /backups
docker compose exec app sh -c 'test ! -w /app'
```

The app service performs migrations and pre-upgrade backups, then supervises
the web server and persistent background-job processor in the same container.

# Production readiness

GameLibrary's production baseline is enforced by `scripts/quality-gate.sh` and
the operational procedures linked below. Product ideas that remain unchecked
in `FEATURE_ROADMAP.md` are post-release enhancements, not release blockers.

## Release criteria

- Locked production dependencies pass `pip-audit` and `pip check`.
- Ruff, focused Mypy checks, source compilation, and the full PostgreSQL test
  suite pass from isolated databases.
- A fresh schema reaches the single Alembic head and the production image
  builds with the authoritative semantic version.
- App and worker use the same image, database, secret keys, and persistent
  mounts. Containers run without root, Linux capabilities, or a writable root
  filesystem.
- Readiness checks include PostgreSQL; liveness remains database-independent.
- Integration credentials are encrypted at rest and have a tested offline key
  rotation procedure.
- A verified database backup and documented asset backup exist before upgrade.

## Deployment checklist

1. Read `DATABASE_MIGRATIONS.md`, `BACKUP_RESTORE.md`, and
   `CREDENTIAL_ENCRYPTION.md`. Preserve the current encryption key.
2. Ensure persistent library and backup directories are owned by UID/GID
   `10001:10001` as described in `CONTAINER_SECURITY.md`.
3. Configure unique high-entropy `SECRET_KEY`, database credentials, and
   preferably `CREDENTIAL_ENCRYPTION_KEY`. Configure `TRUSTED_HOSTS`; set
   `TRUST_PROXY_COUNT` only for the exact trusted reverse-proxy hop count.
4. Put the app behind an HTTPS reverse proxy. Do not expose PostgreSQL publicly.
5. Run `./scripts/quality-gate.sh`, then pull the immutable version tag and
   start Compose. Do not deploy a result built with the container stage skipped.
6. Verify `/health/live`, `/health/ready`, login, an authenticated library page,
   the worker queue, and configured SMTP/Discord/IGDB integrations.
7. Create and validate a post-deployment backup. Monitor structured request logs
   by request ID and review the admin system-event log.

## Rollback

Stop app and worker before database recovery. Restore the verified pre-upgrade
archive and matching library assets, use the same secret/encryption key that was
active when the backup was created, then deploy the prior immutable image tag.
Follow `BACKUP_RESTORE.md`; never downgrade a populated schema ad hoc.

## Accepted deployment boundaries

- TLS termination, certificate renewal, host firewalling, and centralized log
  retention belong to the operator's reverse proxy and host platform.
- High availability and multi-node job execution are not part of the current
  single-instance Compose topology.
- Remaining roadmap items are enhancements. Any future schema, startup,
  security, or recovery change must update `AGENTS.md` and tracked operational
  documentation in the same commit.

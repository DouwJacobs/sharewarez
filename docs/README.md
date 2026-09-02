# Documentation

Durable project documentation lives here. `README.md` at the repository root
covers installation and basic use; this index groups implementation and
operator references by purpose.

## Product and architecture

- [Architecture decisions](ARCHITECTURE.md)
- [Feature roadmap](FEATURE_ROADMAP.md)
- [Game relationships](GAME_RELATIONSHIPS.md)
- [Metadata provenance](METADATA_PROVENANCE.md)
- [Notifications](NOTIFICATIONS.md)
- [System email templates](EMAIL_TEMPLATES.md)
- [UI audit and visual contracts](UI_AUDIT.md)

## APIs and downloads

- [Scoped API tokens](API_TOKENS.md)
- [Public API](PUBLIC_API.md)
- [Download delivery](DOWNLOADS.md)

## Operations and security

- [Production operations](OPERATIONS.md)
- [Production readiness](PRODUCTION_READINESS.md)
- [Local quality gate](LOCAL_QUALITY_GATE.md)
- [Database migrations](DATABASE_MIGRATIONS.md)
- [Backup and restore](BACKUP_RESTORE.md)
- [Container runtime security](CONTAINER_SECURITY.md)
- [HTTP security controls](HTTP_SECURITY.md)
- [Credential encryption](CREDENTIAL_ENCRYPTION.md)

## Maintenance

- Keep instructions aligned with the implementation and update the relevant
  document in the same commit as a behavior or operational change.
- Extend an existing topic document instead of adding dated handover or audit
  files. Preserve dated findings as sections in [UI_AUDIT.md](UI_AUDIT.md).
- Store only screenshots referenced by current documentation.

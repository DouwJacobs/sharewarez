# GameLibrary feature roadmap

This checklist tracks planned product work. A checked item is implemented and
committed; release version bumps are managed separately.

Collection portability uses the versioned `gamestack.collection` JSON format.
Imports revalidate smart rules and skip manual game UUIDs that are unavailable
in the destination library; the completion message reports the skipped count.

## Reliability and operations

- [x] Persistent background-job queue
- [x] Persistent background-job processor with retries, cancellation, and recovery
- [x] Incremental filesystem fingerprints for library scans
- [x] Recurring scan schedules
- [x] Background-job administration page
- [x] Backup, restore, validation, retention, and pre-upgrade snapshots
- [x] Instance health dashboard and integration diagnostics
- [x] Structured, redacted application logging

## Discovery and organization

- [x] Smart collections based on validated library rules
- [x] Nested/grouped collections and collection artwork
- [x] Private versus shared collections
- [x] Collection import/export
- [x] Unified full-text and fuzzy search
- [x] Search suggestions, saved searches, and keyboard navigation
- [ ] Game series, editions, DLC, update, extra, remake, and platform relationships
- [ ] Metadata provenance and conflict resolution

## Users and community

- [ ] In-app notification center
- [ ] Per-event email, Discord, webhook, and in-app preferences
- [ ] Admin-managed templates for welcome, invite, password, request, download, and other user-facing emails
- [ ] Play history and time played
- [ ] Personal ratings, reviews, notes, tags, completion dates, and backlog priority
- [ ] Granular roles and permissions
- [ ] Auditable before/after history for administrative changes

## Downloads and delivery

- [x] HTTP range and resumable downloads
- [ ] Per-user quotas and concurrency limits
- [ ] Bandwidth limits and queue priorities
- [ ] Download expiration and active-transfer monitoring

## Platform and integrations

- [ ] Scoped API tokens
- [ ] Documented public API
- [ ] Outbound event webhooks
- [ ] Metadata-provider abstraction and fallback ordering
- [ ] Library, collection, request, theme, and user-data import/export

## Experience and accessibility

- [ ] Offline-capable PWA library browsing
- [ ] Push notifications and update-available prompt
- [ ] Complete keyboard navigation and dialog focus management
- [ ] Reduced-motion and theme contrast validation
- [ ] Automated accessibility testing
- [ ] Grid, compact-grid, and table library layouts
- [ ] Persistent density and page-layout preferences
- [ ] Mobile bottom navigation

## Engineering foundations

- [x] Single authoritative semantic version
- [x] Versioned CSS cache invalidation
- [x] Automated tag-based container publishing workflow
- [x] Alembic/Flask-Migrate schema migrations
- [x] Locked and audited dependencies
- [x] Required local test, lint, type-check, migration, and container gates
- [x] Non-root hardened container runtime
- [x] Central security headers and rate limiting
- [x] Encrypted integration credentials at rest

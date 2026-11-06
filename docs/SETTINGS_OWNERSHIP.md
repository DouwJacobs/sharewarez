# Settings ownership

Application Settings saves the current category's changed keys. `SECTION_KEYS` in
`sharewarez/utils/settings_sections.py` is the server allowlist; defaults remain
centralized in `settings_defaults.py`.

The current UI posts JSON to `/admin/settings`:

```json
{"section":"downloads","settings":{"downloadBandwidthLimitMbps":0}}
```

`section` is transport metadata and is never persisted. Unknown categories,
extra envelope fields and keys owned by another category return 400. An empty
valid change set is a no-op. Compatible flat JSON clients and POSTs to
`/admin/new_server_settings` still use the same validator/merge path. Numeric zero
retains its documented unlimited/disabled meaning.

| Category | Ownership |
| --- | --- |
| General | Core feature flags and public site URL |
| Scanning | Discovery, supplemental folders and image workers |
| Downloads | Per-user slots, bandwidth, quota, expiry and queue wait |
| Metadata & enrichment | HLTB availability/delay and local metadata/images |
| Interface | Navigation visibility, mobile order and external links |
| Community | Request/issue availability and submission rules |
| Notifications | Automatic event/channel policy |

The UI takes a per-category baseline after initialization and sends only keys
changed from that baseline. Failed saves retain values and validation feedback.
Edits made during a request remain unsaved changes; repeat submissions are guarded.
Inactive controls retain their draft but are disabled for native validation.
Category URLs use `?section=...`; existing category fragments remain accepted.

`locked_settings()` reloads the current settings row with `FOR UPDATE` and
`populate_existing` before merging. When no row exists, a PostgreSQL transaction
advisory lock serializes first creation. Application Settings, archive policy,
branding, site-default theme and metadata mutations share this ownership boundary;
theme deletion also reloads under a row lock before its default-theme fallback.
Existing column mappings, notification-policy side effects and cache invalidation
remain in their respective transaction paths. No schema revision is needed.

## Metadata connections

`utils/metadata_settings.py:apply_metadata_credentials()` is the sole credentials
mutation service, also used by first-run setup. The current provider save route
validates provider order, enablement and available credentials. The legacy
IGDB-specific endpoints normalize their data and delegate to that service.
`/admin/igdb_settings` retains support for incomplete credentials; its GET still
redirects to the provider tab. Credentials-only saves preserve RAWG and provider
order. Blank secret fields retain stored credentials. Secrets remain encrypted
and are omitted from rendered password values; save failures return a bounded
message. Connection-test endpoints remain compatible.

Integrations derives valid destinations from its actual tab buttons. Email,
Webhooks, Metadata providers and Discord restore on reload and history navigation.
`#smtp` aliases Email; `#metadata` aliases Metadata providers. Discord flash routing
uses the same controller, and a valid explicit bookmark takes precedence.

## Completion-time policy

Allow HLTB lookups is a hard global prerequisite. Auto, Manual and Schedule put
optional per-run work in flat Advanced scan options disclosures; cleanup remains
visible. Both HLTB controls are disabled when the global policy is off, with a
link to the owning setting. Worker execution reloads current settings; the HLTB
provider also checks global availability in its own database session. Manual
identification checks the selected per-run option and reads the authoritative
column again before enrichment. A lookup failure cannot undo an identified game.
Scheduled choices remain stored while disabled and recover their meaning when
the policy is enabled again.

## Canonical destinations and compatibility inventory

Application Settings is the single Configure sidebar destination. Existing
Notification rules deep links still open its Notifications category; automatic
rules link separately to Email, Discord and signed outbound Webhooks connections.
The manual Discord group is labelled Manual game notifications.

Application Settings → Downloads owns admission/limit policy, Download delivery
owns people, attempts and reusable links, and Download cache owns archive policy,
shared builds and maintenance. Their links and the administrator guide retain
these distinct tasks, including queue timeout and cache-fallback semantics.

Account Settings edits items per page, sort, sort order, library view and theme,
plus personal notification preferences. Profile links to Browsing and returns to
its Preferences pane. The former profile POST scope remains compatible. Source
inventory found no current modal-opening GET caller; the legacy `?modal=1`
response remains supported, and `preferences_modal.js` continues to submit both
that form and the canonical full-page editor. Other feature, integration and
conditional controls retain their existing runtime readers and write routes.

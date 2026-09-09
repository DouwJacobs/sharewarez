# UI roadmap reconciliation — 8 September 2026

This review reconciles the original UI audit and feature roadmap with the source,
tests, and UI-06 evidence present after release 1.14.1. It distinguishes completed
features from remaining cleanup so future work does not reopen verified behavior.

## Corrected roadmap state

| Roadmap item | Current state | Evidence |
| --- | --- | --- |
| Grid, compact-grid, and list Library layouts | Complete | `library_browser.html` exposes all three controls; `routes_library.py` validates `grid`, `compact`, and `list`; UI-06 renders each at desktop and mobile sizes in three palettes. |
| Persistent density and page-layout preferences | Complete | `/api/preferences/library` persists the selected view in account-scoped experience settings. The settings form exposes the same default, saved views retain filters/layout, and `test_user_experience.py` plus `test_routes_settings.py` cover persistence. |
| Per-event email, Discord, webhook, and in-app preferences | Partial; roadmap remains open | Account-scoped in-app categories and browser-notification preference exist. Per-user email, Discord, and outbound webhook channels do not yet share this preference model. |
| Offline PWA browsing and push/update prompts | Not implemented | Manifest and installable PWA assets exist, but the application does not provide a supported offline Library data/cache contract or push subscription flow. |

All other unchecked roadmap entries remain correctly open. The production gate
passing means they are enhancements, not defects in the published 1.14.1 baseline.

## Source-level UI findings

### R1 — Integration settings shell and controls (complete)

Completed 8 September 2026. The live Integrations workspace and its Discord, IGDB,
and SMTP partials now use the shared administrator page header, consistent action
groups, semantic theme tokens, and one responsive panel hierarchy. Legacy direct
route templates and the Discord help page now use one semantic `main`, the shared
header, and one `app-surface`; the scan-filter validation fallback follows the same
shell and presents table rows as labeled mobile records.

Discord's script now loads through `theme_asset` and scopes its generated Test
webhook action to the Discord form. This prevents it from attaching to SMTP after
the forms adopted a shared action class. The package preserves all endpoints and
form IDs. Verification passed the 88-template accessibility audit, 19 UI contract
tests, and 96 focused Discord/IGDB/SMTP/filter route tests. Default and Ember were
inspected in the disposable browser preview at desktop and mobile breakpoints.

### R2 — System Logs theme and mobile hierarchy (complete)

Completed 8 September 2026. System Logs now uses semantic theme tokens for its
summary cards, filters, table, status badges, expanded event details, pagination,
and clear-log dialog. The desktop table retains one internal horizontal scroll
owner. At the mobile breakpoint, each row becomes a labeled record with Event
promoted above Time, Level, Type, and Actor; actor identity stays in one value
column and unknown levels receive the same neutral badge treatment.

Verification passed the 88-template accessibility audit, 19 UI contract tests,
and all 61 System Logs/system administration route tests. Populated Default and
Ember fixtures were inspected at desktop and mobile breakpoints, including long
events, Debug and Information levels, actor email wrapping, filters, and summaries.

### R3 — Authenticated semantic-shell tail (complete)

Completed 8 September 2026. Edit Update, newsletter detail, and the browser
emulator now have one semantic `main`, a shared page-header macro with one visible
H1, and one primary `app-surface`. Edit Update also removes invalid nested form
labels. Newsletter detail presents delivery metadata as a responsive description
grid and constrains rich message media. The emulator retains its desktop/mobile
workspace height and now explains the placeholder state until media is inserted.

Authentication and setup templates continue to use their dedicated public/setup
shells and remain outside the authenticated `.app-page` contract. Verification
passed the 88-template accessibility audit, 20 UI contract tests, and 41 focused
newsletter, download/play, and update-metadata tests. Populated Default desktop and
mobile views were inspected for all three routes.

### R4 — Theme-token migration is in progress

A conservative static scan still finds direct palette declarations across legacy
route styles. Raw counts include intentional media overlays, shadows, fallbacks,
and semantic warning colors, so they cannot be converted mechanically. The highest
value route-owned targets initially included Game Details, scanning administration,
integration settings, and System Logs. Integration settings, System Logs, Scan
Management, and the effective Game Details storefront are now verified. Remaining
legacy route families still require incremental review. Shared `base.css` and
sidebar values require cross-theme visual regression before replacement.

Scan Management now maps its effective route layer to shared theme roles, uses one
responsive control contract for queue/filter actions, and presents every desktop
table as labeled mobile records. Default, Ember, and Evergreen passed responsive
inspection without document overflow; focused regressions passed for scan status, unmatched
folders, filters, file extensions, and the image queue.

Game Details now overrides the legacy full-width mobile cover rule, keeping artwork
compact and primary actions visible in the first viewport. Its long administrator
menu derives an internal scroll limit from the fixed bottom navigation, so every
shared menu row remains reachable without document overflow. Default, Ember, and
Evergreen passed desktop/mobile inspection and keyboard traversal.

**Rule for follow-up:** migrate one coherent page family at a time, compare Default,
Ember, and a high-luminance palette, and keep canonical/installed theme assets equal.

## Recommended implementation order

1. Incremental route-level theme-token cleanup, one coherent page family at a time.
2. Metadata-provider abstraction as the next larger product feature; keep provider
   integrations API-only and preserve field ownership/provenance.

Phase 1 now provides the normalized discovery boundary, an IGDB API adapter, and
ordered failure fallback for game-request discovery. Image import and refresh now
use the same adapter's normalized media operation, including direct API logo
discovery. Library scan discovery and scalar refresh also use adapter-owned
full-game queries. Provider configuration, provider-neutral stored identities, and
a second API integration remain before the roadmap item can be marked complete.

The current working tree was clean before this reconciliation. No application
behavior, schema, deployment configuration, or published Docker tag is changed by
this documentation pass.

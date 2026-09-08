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

### R2 — System Logs is the clearest remaining table/theme cleanup

The System Logs stylesheet still carries a route-local hard-coded dark palette.
Its table owns horizontal scrolling, which prevents document overflow, but it does
not yet prioritize the event identity/status fields as a compact mobile layout.
Download Delivery, Download Cache, Libraries, Extensions, and Newsletter already
have stronger mobile row/card behavior and should be treated as reference patterns.

**Next package:** replace the hard-coded log palette with semantic theme tokens and
render mobile rows from `data-label` values while retaining the desktop table and
one internal scroll owner.

### R3 — A small semantic-shell tail remains

Most apparent missing H1 results are false positives because `page_header` and
`admin_page_header` render the H1 from a macro. Genuine legacy exceptions include
Edit Update using a `div` page root, newsletter detail using separate containers,
and the browser emulator page having no page heading or semantic main region.
Authentication and setup templates intentionally use their dedicated public/setup
shells and are outside the authenticated `.app-page` contract.

**Next package:** migrate the authenticated exceptions without changing emulator
canvas sizing or newsletter content rendering.

### R4 — Theme-token migration remains broad and should be incremental

A conservative static scan still finds direct palette declarations across legacy
route styles. Raw counts include intentional media overlays, shadows, fallbacks,
and semantic warning colors, so they cannot be converted mechanically. The highest
value route-owned targets are Game Details, scanning administration, integration
settings, and System Logs. Shared `base.css` and sidebar values require cross-theme
visual regression before replacement.

**Rule for follow-up:** migrate one coherent page family at a time, compare Default,
Ember, and a high-luminance palette, and keep canonical/installed theme assets equal.

## Recommended implementation order

1. System Logs theme tokens and mobile information hierarchy.
2. Remaining authenticated semantic page shells.
3. Incremental route-level theme-token cleanup, starting with the pages touched
   by steps 1–2.
4. Metadata-provider abstraction as the next larger product feature; keep provider
   integrations API-only and preserve field ownership/provenance.

The current working tree was clean before this reconciliation. No application
behavior, schema, deployment configuration, or published Docker tag is changed by
this documentation pass.

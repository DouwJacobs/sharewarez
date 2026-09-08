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

### R1 — Legacy integration pages still bypass the shared page shell

The Discord settings/help, IGDB settings, SMTP settings, and scanning-filter
templates use legacy Bootstrap containers/cards rather than one semantic `main`,
the shared administrator page header, and a single themed surface. Several use an
H2 as the page title. Discord settings also loads its JavaScript from the installed
default-theme path instead of `theme_asset`, so a custom theme cannot override it.

**Next package:** migrate these related administration pages together, preserve
their existing forms and endpoints, and verify Default, Ember, and a light palette
at 1440 × 1000 and 390 × 844.

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

1. Shared-shell migration for Discord, IGDB, SMTP, and scanning filters.
2. System Logs theme tokens and mobile information hierarchy.
3. Remaining authenticated semantic page shells.
4. Incremental route-level theme-token cleanup, starting with the pages touched
   by steps 1–3.
5. Metadata-provider abstraction as the next larger product feature; keep provider
   integrations API-only and preserve field ownership/provenance.

The current working tree was clean before this reconciliation. No application
behavior, schema, deployment configuration, or published Docker tag is changed by
this documentation pass.

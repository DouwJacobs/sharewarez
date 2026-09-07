# UI audit

This is the durable record of the application's UI contracts and dated audit
passes. Completed follow-up findings are folded into this document so there is
one source of truth for current layout and visual guidance.

Audit date: 2026-08-09  
Branch: `audit/ui-consistency-fixes`  
Application: local WSL development instance at `http://localhost:5006`  
Viewports: desktop 1440 × 1000; mobile 390 × 844  
Theme observed: Evergreen/custom dark-green theme

## Automated accessibility gate

`scripts/accessibility_audit.py` scans every Jinja template for baseline accessibility contracts, including document language, alternative text, accessible interactive names, labelled form controls, iframe titles, dialog semantics, and duplicate static IDs. The production quality gate runs this audit before the test suite, and `tests/test_accessibility_audit.py` verifies both the full template tree and each failure mode.

The library's desktop-only hover preview uses a layered storefront surface with 16:9 artwork, concise metadata, bounded chips, edge-aware placement, and reduced-motion support. Touch and mobile layouts do not render hover-only content.

## Method

The Flask route map was enumerated first. Page-producing GET routes were separated from APIs, downloads, static assets, and state-changing actions. Each concrete page below was then loaded in an authenticated administrator session at desktop and mobile widths. The audit checked the visible layout, content bounds, horizontal overflow, navigation, spacing, responsive stacking, control density, and computed theme colors. Key screens were also visually compared as screenshots.

Dynamic routes were exercised with existing representative records: one game, one library, and the existing populated download table. No forms or destructive actions were submitted.

## Page inventory and coverage

### Public and authentication

| URL | Page | Audit status |
| --- | --- | --- |
| `/login` | Sign in | Redirected because the audit session was already signed in; template reviewed |
| `/register` | Registration | Redirected in the authenticated session; template reviewed |
| `/reset_password_request` | Password reset request | Template/route inventory only |
| `/reset_password/<token>` | Password reset | Token-dependent; template/route inventory only |
| `/confirm/<token>` | Email confirmation | Token-dependent; template/route inventory only |
| `/setup` | Initial setup | Existing installation redirects/blocks setup; template inventory only |
| `/setup/igdb` | Setup: IGDB | Existing installation; template inventory only |
| `/setup/smtp` | Setup: SMTP | Existing installation; template inventory only |
| `/offline` | PWA offline page | Desktop and mobile inspected |
| `/restricted` | Restricted-area notice | Desktop and mobile inspected |

### User-facing pages

| URL | Page | Audit status |
| --- | --- | --- |
| `/`, `/index` | Home alias | Redirects to `/discover`; alias verified |
| `/discover` | Discovery home | Desktop and mobile inspected |
| `/library` | Game library | Desktop and mobile inspected |
| `/libraries` | Library list | Desktop and mobile inspected |
| `/browse_games` | Legacy browser response | Route loaded; produces a non-page/empty response in this state |
| `/game_details/<game_uuid>` | Game details | Desktop and mobile inspected with an existing game |
| `/game_edit/<game_uuid>` | Edit game metadata | Desktop and mobile inspected with an existing game |
| `/edit_game_images/<game_uuid>` | Edit game images | Desktop and mobile inspected with an existing game |
| `/add_game_manual` | Add game manually | Desktop and mobile inspected |
| `/favorites` | Favorites | Desktop and mobile inspected |
| `/trailers` | Random trailers | Desktop and mobile inspected |
| `/requests` | Game requests | Desktop and mobile inspected |
| `/downloads` | User downloads | Desktop and mobile inspected |
| `/help` | Help and FAQ | Desktop and mobile inspected |
| `/settings_panel` | Preferences | Desktop and mobile inspected |
| `/settings_profile_view` | Profile | Desktop and mobile inspected |
| `/settings_profile_edit` | Edit profile | Desktop and mobile inspected |
| `/settings_password` | Change password | Desktop and mobile inspected |
| `/user/invites` | Invite friends | Desktop and mobile inspected |
| `/scan_management` | Scan management alias | Desktop and mobile inspected |
| `/play_game/<game_uuid>` | Webretro player | Format/data-dependent; route inventory only |
| `/playromtest` | Webretro test player | Route inventory only |

### Administration

| URL | Page | Audit status |
| --- | --- | --- |
| `/admin/dashboard` | Admin dashboard | Desktop and mobile inspected |
| `/admin/libraries` | Libraries | Desktop and mobile inspected |
| `/admin/library/add` | Add library | Desktop and mobile inspected |
| `/admin/library/edit/<library_uuid>` | Edit library | Desktop and mobile inspected with an existing library |
| `/admin/scan_management` | Scan management | Desktop and mobile inspected |
| `/admin/manage-downloads` | Download requests | Desktop and mobile inspected with populated table |
| `/admin/game-requests` | Game requests | Desktop and mobile inspected |
| `/admin/game-requests/<request_id>` | Request details | Record-dependent; inventory only |
| `/admin/settings`, `/admin/new_server_settings` | Server settings | Redirect and destination inspected at both widths |
| `/admin/new_server_info`, `/admin/server_status_page` | Server status/info | Both routes inspected at both widths |
| `/admin/system_logs` | System logs | Desktop and mobile inspected |
| `/admin/statistics` | Statistics | Desktop and mobile inspected |
| `/admin/users` | User management | Desktop and mobile inspected |
| `/admin/manage_invites` | Invitation management | Desktop and mobile inspected |
| `/admin/whitelist` | Whitelist | Desktop and mobile inspected |
| `/admin/collections` | Collections | Desktop and mobile inspected |
| `/admin/collections/new` | Add collection | Form variant; inventory only |
| `/admin/collections/<collection_id>/edit` | Edit collection | Record-dependent; inventory only |
| `/admin/discovery_sections` | Discovery sections | Desktop and mobile inspected |
| `/admin/image_queue` | Image queue | Desktop and mobile inspected |
| `/admin/branding` | Branding | Desktop and mobile inspected |
| `/admin/themes` | Themes | Desktop and mobile inspected |
| `/admin/themes/builder`, `/admin/themes/builder/<theme_id>` | Theme builder | New-theme variant inspected at both widths; edit variant inventory only |
| `/admin/attract_mode_settings` | Attract mode | Desktop and mobile inspected |
| `/admin/extensions` | File extensions | Desktop and mobile inspected |
| `/admin/integrations` | Integrations | Desktop and mobile inspected |
| `/admin/igdb_settings` | Legacy IGDB settings | Desktop and mobile inspected |
| `/admin/smtp_settings` | Legacy SMTP settings | Desktop and mobile inspected |
| `/admin/discord_settings` | Legacy Discord settings | Desktop and mobile inspected |
| `/admin/discord_help` | Discord help | Desktop and mobile inspected |
| `/admin/edit_filters` | Filters | Desktop and mobile inspected |
| `/admin/newsletter` | Newsletter | Desktop and mobile inspected |
| `/admin/newsletter/<newsletter_id>` | Newsletter detail | Record-dependent; inventory only |
| `/admin/help` | Administrator guide | Desktop and mobile inspected |

API endpoints, file responses, PWA assets, progress polling routes, download routes, and POST/DELETE actions are intentionally excluded from the visual page inventory.

## Findings

### P1 — Favorites lost its page-specific styling after the homepage redesign

Commit `623bbdf` replaced the Discovery homepage stylesheet and removed the Favorites rules that had been colocated there. The Favorites template continued loading `discover.css`, leaving its header, empty state, and card layout effectively unstyled at both desktop and mobile widths.

Status: fixed by reconnecting the dedicated `favorites.css`, rebuilding it around current theme tokens, restoring the centered empty state, and aligning populated cards with the stable 3:4 Library card layout. Verified at 1440 × 1000 and 390 × 844 with no document-level horizontal overflow.

### P1 — Library cards collapse when artwork is missing or still loading

On `/library`, cards whose image did not establish a height collapsed to their controls/title. On mobile this caused several game titles and floating card controls to overlap in the same vertical area; desktop showed a row of title-only entries beneath the first loaded covers. The card needs a stable poster aspect ratio independent of image success.

Status: first fix implemented by giving `.game-cover` a 3:4 aspect ratio and theme-aware fallback surface.

### P1 — Admin dashboard overrides the active page theme

`/admin/dashboard` explicitly used `--admin-bg-dark`, producing a neutral charcoal content canvas while the sidebar, other admin pages, and the active Evergreen theme used a dark green page canvas. This was the clearest cross-page theme inconsistency.

Status: first fix implemented by using `--theme-page-bg`/`--body-bg` and theme primary text tokens.

### P2 — Desktop content gutters are inconsistent

Most modern pages begin around 296–320 px with the expanded sidebar, but several narrow forms use centered fixed-width content (`/settings_panel` around 518 px and `/settings_password` around 578 px), `/restricted` begins around 408 px, and some legacy pages do not use a semantic `<main>`. The centering is reasonable for forms, but the page-header and top-spacing system is not consistently shared.

Recommendation: introduce/reuse one page shell for the common 1200–1440 px canvas and one explicit narrow-form modifier. Migrate legacy pages gradually instead of adding more page-specific margins.

### P2 — Theme tokens are bypassed in page CSS

The active theme generally propagates well, including navigation, cards, forms, buttons, and tables. However, the audit found page-level hard-coded white/blue RGBA values in the library header and fixed admin colors. These can look acceptable in one dark theme but do not guarantee contrast or visual identity in other themes.

Status: library header text/accent tokens and admin dashboard background were converted in the first pass. Continue auditing hard-coded colors against the theme builder's page, panel, card, text, accent, border, success, warning, and danger tokens.

### P2 — Wide admin tables depend on internal horizontal scrolling

`/admin/manage-downloads` and `/admin/system_logs` contain tables wider than the content panel. The page itself does not acquire horizontal overflow, which is good, and the download table exposes an internal scrollbar. On mobile, the download controls stack successfully, but the visible table becomes a narrow viewport into many columns and the Audit log label wraps awkwardly.

Recommendation: keep the scroll container but prioritize or hide low-value columns at small widths, keep primary identity/status/actions sticky or first, and prevent short action labels from breaking mid-word.

### P2 — Mobile top spacing varies by page family

User pages generally start at 84–99 px below the compact header. Admin pages with the shared admin header start around 129–134 px. This is internally consistent by family, but transitions between user and admin areas feel noticeably different.

Recommendation: formalize two spacing tokens (standard and admin-with-breadcrumb) and ensure every page uses one intentionally.

### P3 — Page titles and semantic structure are inconsistent

Several pages retain the generic site title and/or lack a semantic `<main>`/visible `<h1>`: legacy integrations/settings pages, library add/edit forms, downloads/help, and some scan pages. This weakens navigation context, accessibility, and automated regression checks.

Recommendation: give every page a specific document title, one visible H1, and a semantic main region. Prefer the shared eyebrow/title/description pattern already used by the redesigned pages.

### P3 — Discovery carousel content is intentionally off-canvas

Desktop measurement finds later discovery cards beyond the viewport, while document width remains constrained. This is an intentional horizontal carousel rather than page overflow. Ensure the arrow/scroll affordance remains visible and keyboard-accessible in every theme.

## Cross-page observations

- The responsive sidebar behaves consistently: expanded at desktop and fully off-canvas at mobile, with a compact menu button and search field.
- No audited mobile page produced document-level horizontal scrolling at 390 px.
- The common dark theme is broadly coherent across user and admin screens after excluding the dashboard override.
- Cards, panels, inputs, buttons, and tables mostly respect the current accent colors.
- Mobile layouts generally stack correctly; the most serious visual failure was the unstable library card height.
- Desktop pages typically maintain 24–40 px content padding, while mobile pages typically maintain about 12 px outer gutters.

## Implementation queue

1. Stabilize library poster/card dimensions and verify missing-image behavior. **Started**
2. Remove the admin dashboard page-background theme override. **Started**
3. Improve mobile admin table column priority and action-label wrapping.
4. Consolidate common page-shell widths, gutters, headings, and top spacing.
5. Replace remaining hard-coded colors in page CSS with theme tokens.
6. Add semantic main regions and specific document/H1 titles to legacy pages.
7. Add screenshot regression coverage for `/discover`, `/library`, a game detail page, `/admin/dashboard`, `/admin/manage-downloads`, and `/admin/themes/builder` at desktop and mobile widths.

## Re-audit checklist

- Run `pyenv activate sharewarez` and `./startweb.sh --reload`.
- Test at 1440 × 1000 and 390 × 844.
- Check the default theme plus at least one light/high-luminance custom theme and one dark custom theme.
- Verify missing/broken covers on the library do not collapse card height.
- Verify every page stays within the document viewport; tables/carousels may use intentional internal scrolling.
- Compare standard/admin page gutters, top spacing, H1 styles, and breadcrumbs.
- Confirm buttons, focus rings, muted text, status chips, and destructive actions meet contrast expectations.
## Admin operations UI follow-up (2026-08-09)

- `/admin/integrations` previously inherited a global `.card { width: 70% }` rule from the SMTP stylesheet, nested several card surfaces, and rendered all settings in one tall column. It now has a dedicated responsive page shell, segmented service tabs, flatter panels, and two-column fields on desktop that collapse to one column on mobile.
- `/admin/new_server_info` previously combined centered legacy status styles, five narrow diagnostic columns, and a long single-column sequence of tables. It now uses a left-aligned status header, three-column diagnostic cards, four-column resource cards, a two-column information grid, and bounded scrollable tables. All structures collapse without horizontal overflow at 390px.
- Integration detail forms remain the canonical place to configure and test SMTP, Discord, and IGDB; Server Info remains a read-only diagnostic summary.

## Unified responsive layout contract (2026-08-11)

The previous mobile implementation mixed route-owned margins, Bootstrap container gutters, and a shared `#content` gutter. Depending on the route, this produced zero, one, two, or three horizontal insets. Several route styles also flattened page cards after the shared mobile stylesheet had loaded.

All new and migrated authenticated layouts now use these structural primitives from `components.css`:

- `.app-page`: desktop rail and mobile page shell. On mobile it fills the width available inside the single 12 px `#content` gutter.
- `.app-page-header`: shared title, description, count, and action alignment.
- `.app-page-actions`: wrapping desktop/mobile action group.
- `.app-surface`: themed bordered card with shared radius, shadow, and responsive padding.
- `.app-stack` and `.app-grid`: shared inter-surface spacing.

Primary user pages, modern admin pages, and the most visible legacy container-based admin pages have been migrated. Route-specific classes remain for content layout and identity only; they should not introduce viewport-relative mobile widths or horizontal margins. The explicit selector group in `mobile.css` is a compatibility adapter for remaining legacy templates and should shrink as those templates are touched.

When adding or revising a page:

1. Put `.app-page` on the outer authenticated page wrapper.
2. Use one `.app-page-header` for the visible H1 and page actions.
3. Put each major content region in `.app-surface`; use `.app-stack` when there is more than one.
4. Do not add `width: calc(100% - ...)`, `margin-inline`, or Bootstrap `.container` padding at the mobile breakpoint.
5. Keep tables and rails internally scrollable rather than widening the page.

## Game details storefront contract (2026-08-11)

`/game_details/<uuid>` now uses the same storefront language as Discover while preserving the established download, play, extras, update-request, favorite, status, NFO, screenshot, and administrative actions.

- `.game-details-page` uses the shared wide application rail.
- `.game-storefront` is a deliberate full-bleed media surface: available screenshot artwork is preferred for its backdrop, with cover artwork as the fallback.
- The hero establishes ownership, title, release/developer/genre context, cover art, ratings, searchable facts, and one distinct acquisition shelf.
- Description, installation instructions, screenshots, and videos follow below the purchase area instead of competing with the primary actions.
- At mobile widths, `#content` remains the sole 12 px viewport gutter. The storefront fills that available width, facts use two compact columns, the acquisition shelf stacks, and media remains internally horizontal.
- Legacy JavaScript hooks and dialog IDs remain stable. Storefront work must not remove keyboard focus trapping, Escape behavior, or trigger-focus restoration.
# Admin multi-section workspaces

Admin pages with multiple configuration areas use a consistent focused-workspace pattern: a descriptive category rail beside one active content panel. On mobile, the rail becomes a horizontally scrollable selector. The reusable `.admin-tab-workspace`, `.admin-tab-nav`, `.admin-tab-link`, and `.admin-tab-content` primitives live in the default theme `components.css`; Server Settings uses the equivalent interactive settings workspace, while Integrations and Scan Manager retain Bootstrap tab semantics through these shared presentation classes.

## Admin information architecture and visual re-audit (2026-08-23)

The administrator area now has one categorized destination registry in `sharewarez/utils/admin_navigation.py`. The persistent rail and global search both consume that registry, preventing navigation and search ownership from drifting apart. Destinations are grouped by operator intent:

- Overview: work requiring attention and instance health.
- Library: libraries, scanning, collections, and Discovery ordering.
- Community: game requests, game issues, and download activity.
- People: users, invitations, and registration whitelist.
- Operations: jobs, logs, server status, and statistics.
- Configure: application policy, notification rules, integrations, branding, themes, attract mode, newsletter, and email templates.

Application Settings owns global behavior and notification event policy. Integrations owns SMTP, Discord, and IGDB credentials/testing. Scan Manager owns filters, extensions, image queue, and scan jobs. The old settings, integration, scan-tool, and status URLs remain authenticated compatibility endpoints but redirect GET requests permanently to their canonical workspace and tab.

The dashboard was reduced to a compact status strip, a single attention list, instance health, and three frequent actions. It intentionally avoids decorative metric cards, repeated directory links, gradients used as ornament, and duplicated navigation. Discovery Sections, Invitations, Whitelist, and Attract Mode were migrated from legacy presentation to the shared page header and surface system. Decorative whitelist artwork was removed.

Visual verification used the live authenticated application with computer vision at the default desktop viewport, 1024 × 900, and 390 × 844. Default, Ember, and Midnight Cyan themes were checked; the original Midnight Cyan preference was restored afterward. All 23 top-level admin destinations were loaded at 390 px and checked for one visible H1, document-level horizontal overflow, and visible elements escaping an unclipped container. No failures were found. Wide tables and horizontal selectors retain intentional internal scrolling. The mobile admin destination rail is a single horizontally scrollable row, not a multi-row block.

Shared interaction details verified in this pass:

- opening one admin category closes any previously open category;
- clicking outside or pressing Escape closes the active category menu;
- adjacent email-template panels have equal measured height on desktop;
- the whitelist email control remains full width at mobile and desktop sizes;
- Discovery ordering rows retain an 8 px visual gap and independent focus/drag boundaries;
- the collapsed sidebar keeps its notification bell centered and overlays the unread count at the bell's upper-right corner.

## Default-theme accent normalization (2026-08-24)

The default theme has one canonical indigo accent: `--theme-accent-rgb: 98, 122, 239`, with
`--theme-accent-soft-rgb: 154, 177, 255` for lighter emphasis. Legacy `--theme-primary`,
`--btn-primary`, form-focus, brand-surface, and brand-shadow variables resolve through those
tokens. New navigation, action, focus, selection, or decorative emphasis styles must use the
canonical aliases instead of introducing Bootstrap blue, royal blue, or cyan literals.

Blue remains valid when it carries explicit semantic meaning, such as an informational alert,
log level, transfer/scan state, or provider-specific branding. Semantic colors must use the
existing `--semantic-*` aliases so changing a theme accent does not change status meaning.

## Cross-application restraint pass (2026-08-24)

The user and administrator interfaces now share a quieter presentation contract:

- Accent color is reserved for the current destination, primary actions, selection, and focus.
  Inactive navigation, search, quick-action, and decorative icons use secondary text color.
- Discover keeps one featured story and a compact divided collection summary. Shortcut
  collections are collapsed behind a native disclosure instead of competing with the hero.
- Library cards show one predictable metadata row and do not repeat file size. Sort remains
  immediately available while advanced filters live behind one accessible disclosure button.
- Play state, request state, issue state, invitations, whitelist entries, and access tokens use
  the shared neutral, active, success, warning, and danger status tokens.
- Empty results use the shared empty-state structure, and asynchronous card loading uses the
  shared skeleton primitive. Both remain theme-token-driven.
- `.app-page` uses a short opacity/translate entry transition. The transition and skeleton
  shimmer are disabled when `prefers-reduced-motion: reduce` is active.
- Scan Management keeps one page surface; the active workspace panel is flattened so internal
  field groups do not appear inside several equally weighted cards.

Responsive verification covers the 390 px contracts in automated tests, including page width,
filter wrapping, bottom-navigation clearance, single-instance game actions, and reduced-motion
rules. Live authenticated desktop checks cover Discover, Library, Game Details, Requests,
Issues, Admin Overview, and Scan Management without document-level horizontal overflow.

## Shared control and single-surface audit (2026-09-02)

The authenticated UI was re-audited across 38 current user and administrator destinations at 1440 × 1000 and 390 × 844. The pass focused on control height, alignment, input padding and presentation, nested surface hierarchy, and document-level horizontal overflow.

- Ordinary text inputs, native selects, and action buttons now use `--app-control-height`: 42 px on desktop and 44 px on mobile. Purpose-built geometry such as carousel dots, drag handles, compact icon toggles, colour/range controls, and multi-line workspace navigation remains intentionally distinct.
- Text and select controls share the themed input border, background, radius, foreground, and 12 px inline padding. Their text is left aligned; action-button content is centered on both axes.
- Text inputs use the flatter inset shadow established by native selects. Selects use one theme-accent chevron with a 16 px visual end gutter, preserving their purpose without changing the shared fill, border, radius, size, or type treatment. The Username and Transfer Status controls on administrator Download Delivery were used as the reference pair.
- Empty states placed directly inside `.app-surface` are now content rather than another bordered, filled, shadowed card. This removes the nested empty card previously visible on Favorites and applies the same hierarchy to Downloads and other shared empty-state variants.
- Table and DataTables overflow wrappers inside `.app-surface` retain their scrolling responsibility but no longer repeat the parent surface's border, background, radius, or shadow. The Downloads page therefore presents one high-level panel instead of a panel containing a second table card.
- The Requests search field is intentionally a borderless, transparent inner control within its single 40 px search shell. Its scoped override prevents the shared input contract from adding a second border, fill, shadow, or 42 px height inside that shell.
- The setup-theme source and installed default-theme assets remain synchronized.

Post-change computed-style verification found no contract failures or document-level horizontal overflow on the 38 audited destinations at either viewport. Visual checks covered Favorites, user Downloads, Add Library, and administrator Download Delivery.

## Resumable download cache UI (2026-09-02)

The dedicated `/admin/download-cache` Operations page uses three sibling
`.app-surface` sections for storage health, policy, and archive inventory. It
reuses shared controls and semantic status pills; no source path is shown
outside the administrator surface. The member Downloads page now labels
stable files and ready cached archives as resumable, shows archive preparation
progress, and keeps the live-stream fallback explicit about restart behavior.
Queued and running inventory rows expose a destructive Cancel action; while a
running worker winds down, the disabled label changes to **Cancelling…** and
the progress text continues to report its current stage.

The authenticated page was visually checked at 1440 × 900 and 390 × 844 in the
installed default dark theme. The desktop inventory owns its one horizontal
table surface. At 390 px entries become compact record cards, low-priority size
columns are omitted, and Pin, Retry, and Evict remain reachable without
document-level horizontal overflow. The single mobile gutter and bottom-nav
clearance remain intact. No light theme is installed in this workspace, so a
light-theme visual pass was not available; all route styles use shared theme
tokens rather than dark palette literals.

## Active transfer monitor refresh (2026-09-03)

The administrator Download Delivery monitor uses one non-overlapping refresh
loop, pauses network requests while its tab is hidden, and refreshes immediately
when the administrator returns. Transfer data is explicitly non-cacheable. The
elapsed clock advances locally once per second between server responses and uses
compact durations such as **17m 16s** or **2h 14m** instead of an ever-growing
raw seconds value. Existing transfer rows remain visible during a transient
refresh failure.

Member transfer polling is also non-overlapping and visibility-aware. It uses a
two-second interval while a transfer is active and a ten-second idle interval.
The Download Cache summary uses a three-second active interval and a thirty-second
idle interval, reducing background work without making running builds feel stale.

## SSE administrator monitor (2026-09-04)

The active-transfer monitor now uses stable transfer-ID nodes, updates changed
text in place, and leaves selected text untouched until selection ends. It shows
eight-second current speed, per-attempt average speed, and meaningful ETA alongside
the elapsed clock. A small status line announces connection changes; rapidly
changing transfer counters are not an ARIA live region. Progress transitions and
indeterminate animation explicitly honor reduced motion.

`download_live.js` owns SSE, reconnect/watchdog handling, non-overlapping polling
fallback, visibility pause/resume and back-forward-cache restoration. The admin
monitor is its first consumer; user Downloads and archive inventory integration
remain pending. The setup-theme and installed default-theme copies are synchronized.

A disposable PostgreSQL-backed preview (`python -m tests.preview_download_live`,
with an empty `TEST_DATABASE_URL`) simulated an 8 MiB/s transfer through real
database notifications and the authenticated ASGI endpoint. Screenshots were
inspected at the default desktop viewport, 1440 × 1000 and 390 × 844. Mobile
computed bounds confirmed the single 12 px gutter and no document-level overflow.
An entered Username filter and focus survived updates. No browser console errors
were observed. The temporary viewport was reset. Other themes, actual WAN rates,
user Downloads and cache inventory are not covered by this stage's visual check.

Transport behavior is tested with `node tests/download_live.test.cjs`; Python
route tests verify script wiring. On Windows, invoke the test file directly rather
than `node --test` when using a UNC repository path.

## SSE member Downloads transitions (2026-09-04)

The member page now uses the shared SSE client and polling fallback. Visible
request IDs are subscribed in one stream. Status, archive progress, delivery
label, expiry, size, transfer state and the page summary update without a page
reload. All action forms are server-rendered with CSRF tokens and remain stable;
only their visibility changes. If a focused action becomes invalid, focus moves
to that row's status cell without scrolling. Expired/failed links expose Retry;
ready cached archives expose Download and the Resumable label.

The scoped hidden-action rule deliberately outranks shared button geometry:
otherwise the shared `display: inline-flex !important` rule makes a hidden link
visible. This conflict was caught in the rendered preview and fixed. Preparation
percentages no longer announce every update through a live region.

A cycling disposable archive fixture demonstrated Preparing → Ready in the open
page without navigation, with Cancel hidden and Download visible afterwards.
Default-theme desktop and 390 × 844 screenshots were inspected. Mobile remained
within 390 px, with the shared 12 px gutter. No browser console errors were found.
The fixture contains synthetic metadata only; it does not claim to validate the
contents of a delivered archive. Other-theme and real-interruption testing remain
part of the full implementation verification.

## SSE cache inventory (2026-09-04)

The inventory now updates the visible archive rows' state, build-job stage,
percentage, bytes, failure message, pin state, last-used time and active-transfer
count. Cancel/Retry visibility and Evict availability change in place. Server
forms retain their CSRF tokens and confirmation prompts. Policy and filter fields
are not refreshed, and a changed inventory count offers an explicit refresh link
instead of reordering the current page beneath the administrator.

The preview exposed a PostgreSQL aggregate Decimal serialization issue: the SSE
stream failed while polling remained usable. Totals are now converted to integers
and tested with the same JSON encoder as ASGI. After restart, the rendered status
confirmed **Live updates connected** and stage/progress updates continued.

Mobile 390 × 844 inspection caught progress subtext occupying the narrow label
column; the scoped rule now keeps archive metadata and stage text in column two.
The mobile page has its single 12 px gutter and no document-level overflow. An
unsaved retention value of 14 survived live updates. Desktop inventory and policy
layout were also checked in the default theme. No real cache files were built,
cancelled or evicted by the synthetic UI fixture.

## Game image editor fixes (2026-09-04)

The editor now links back to its game and offers an explicit IGDB refresh with
progress and failure feedback. Key art and standalone logos have labelled file
and style controls, using the existing default-selection actions. Uploads accept
PNG, JPEG, GIF and WebP, preserve transparency, validate categories and actual
file size, and mark local files downloaded.

New imports query the direct IGDB artwork collection, merging it with the game's
artwork references; refreshes also merge both sources. Existing libraries can use
Refresh from IGDB to retrieve logos added since their original import. A live
Hogwarts Legacy refresh recovered its missing color logo successfully.

The authenticated default-theme editor was inspected at the default desktop
viewport and 390 × 844. Upload controls wrap, mobile selects and action buttons
measure 44 px, the single mobile gutter remains, and there is no horizontal
overflow. Back to game navigation was exercised. The viewport was reset.
Other theme variants were not visually re-audited. Python regressions cover all
five curated upload types, transparency, default selection, invalid categories,
and discovery of logos absent from the nested game artwork list.

## Full-stack audit (2026-09-05)

See [the full audit report](FULL_AUDIT_2026-09-05.md) for reproduced backend,
security, UX and performance findings and synthetic evidence. Library filter
removal, count synchronization and AJAX attribute escaping require follow-up.
Metadata editing lacks an H1; metadata/image editing and Download Cache retain
generic document titles. Mobile and desktop document-width measurements passed,
but repeated browser screenshot timeouts prevented a completed visual/contrast
review. No UI fixes were applied in this pass. A theme test unexpectedly deleted
the installed default theme; it was restored from canonical source and compared
for equality. The report records the test-isolation and theme-reset defects.
### Audit fixes — 5 September 2026

Library initial and AJAX cards share `games/library_cards.html` and escaped metadata.
The shared action-menu template is fetched on demand; maintain its admin boundary
and keyboard Escape/focus behavior. URL filters are authoritative when `filters=1`
or filter parameters are present; zero rating includes unrated titles. Option lists
populate independently. Browser desktop/mobile and apply/remove/paginate checks pass.
Activation recovery has a working rate-limited resend route and 44 px mobile controls.
Metadata editing uses an H1; image edit and download-cache pages have specific titles.
See the remediation ledger for full-suite and remaining verification status.


### Completed remediation visual follow-up — 6 September 2026

The screenshot tooling recovered. Default-theme Library, metadata/image editors,
activation resend and Download Cache were reviewed on desktop and 390 × 844;
Ember Library was reviewed with isolated synthetic data. No horizontal overflow
was found on these pages. Metadata field groups and details are flat within the
shared outer surface, with one primary Save action. Mobile ordinary actions are
44 px. Library menu replacement restores the old card controls, Escape returns
focus, and saved layouts retain the selected view in the URL. The remediation
ledger records security probes, performance results and verification limits.


## Responsive consistency inspection — 6–7 September 2026

The inspection covered 49 authenticated URL variants at 1440 × 1000 and
390 × 844, plus sign-in, registration, and password-reset request screens.
The normal WSL development server on port 5006 was offline. Browser verification
used an isolated PostgreSQL-backed preview on port 5008 with synthetic records;
no production library, account, or configuration was changed.

Changes and current contracts:

- Favorites and Library now share `games/library_cards.html`, the Library grid
  stylesheet, and `serialize_library_cards()`. Cover fallback, escaped title,
  action menu, play state, and favorite controls come from the same sources.
  The obsolete mobile Favorites page-card override was removed. Favorites uses
  the same single panel/header arrangement as Library, without a separate frame
  around the game grid.
- Favorite toggles behave identically on Library, Favorites, and Game Details.
  They use the existing notification system, expose pressed/busy state, prevent
  duplicate pending requests, and synchronize duplicate controls. Removed
  favorites stay on the current page until navigation/reload so they can be
  toggled back immediately, just as on Library. Reload reflects persisted state.
- Ordinary buttons share height (42 px desktop, 44 px mobile), radius, type size,
  inline padding, centered content, and gap. They no longer scale or move on
  hover. Hidden attributes, Bootstrap hiding, inline JavaScript visibility, and
  disabled states remain authoritative. Keyboard focus has a themed outline.
- Request search shells now follow ordinary control height while their inner
  inputs remain borderless. Select chevrons use theme text tokens.
- Edit/navigation actions use secondary styling; deletion and destructive restore
  actions use danger styling. Authentication navigation is secondary, including
  password recovery. Long Attract Mode forms retain Save at both ends, with the
  same label and size. Authentication headings and labels are consistent.
- Theme operations and installed-theme groups, the nested Scan Manager tab
  panels, Discord connection form, Attract Mode field groups, and the mobile
  Newsletter shell no longer add redundant elevated panels.
- Narrow viewports expose card controls even when the device has a mouse. Image
  replacement is a keyboard-operable ordinary button with a labelled file input.
- The manual identification page has a specific document title. The email
  templates description no longer hard-codes an incorrect template count.
- The trailer inspection exposed a PostgreSQL whole-row DISTINCT failure on JSON
  game metadata. ORM identity deduplication now preserves genre/theme join
  behavior without comparing JSON columns; a real PostgreSQL regression covers it.
  Empty/error states clear the stale game link and loading heading.

Coverage: profile/view/edit/password/preferences, invitations, Discover, Library,
Favorites, activity, requests, issues, downloads, notifications, trailers, help,
library list/add/edit, game details/metadata/images/manual identification, and
administrator overview, scanning, collections/new, discovery ordering, requests,
issues, delivery, users, invitations, whitelist, cache, jobs, logs, server status,
statistics, settings/notification rules, integrations, branding, themes/builder,
attract mode, newsletter, and email templates. Scan Manager's six categories and
all three integration categories were also exercised. Newsletter and Server
Status were enabled only in the disposable fixture to inspect their real routes.

The final 98 authenticated viewport checks found no document overflow or visible
hidden controls. Ordinary button heights passed after waiting for the email
editor stylesheet to settle (an initial pre-load measurement was transient).
Screenshots were inspected for representative member/admin pages and all changed
page families. Favorites menu open/Escape/focus restoration and reversible favorite
toggling were exercised. Default and Ember themes were inspected; the fixture's
default theme was restored and the temporary viewport reset.

Limits: populated production-scale grids, real external integration calls,
state-changing admin operations, initial setup, token-dependent authentication
completion pages, and data-dependent request/issue/collection detail variants
were not exercised end to end. No light theme was available for a visual pass.
This is a broad responsive/component audit, not a claim that every possible
application state or contrast combination has been tested.

Verification: 87 focused Python UI/accessibility/mobile/Library/favorite route
regressions passed; six JavaScript favorite success/failure/concurrent-control cases;
Ruff and `git diff --check`. Canonical and installed changed theme files match.

## Remaining UI handoff implementation — 7 September 2026

UI-01 through UI-05 and the user-requested Game Edit rework (UI-07) in
`UI_IMPLEMENTATION_HANDOFF.md` are implemented. UI-06 remains the broader
populated-state and theme validation pass.

- Popup action anchors and buttons now share one left-aligned row contract. A
  populated synthetic IGDB link measured the same 223.25 × 46.68 px as an
  adjacent desktop button and 188.11 × 46.03 px at 390 px. Destructive rows use
  the shared danger token and asynchronous
  Discord/move failures use the application notification system.
- One popup close function handles Library cards and the Game Details cover.
  A rendered Escape check closed the menu, cleared both container states,
  restored hidden controls, set `aria-expanded` to false, and focused the trigger.
- Mobile card layouts reserve enough cover width for two 44 px top actions. Grid,
  compact, and list were measured at 390 px; compact and list were repeated at
  320 px. No targets overlapped and document width matched the viewport.
- The mobile Game Details favorite control now participates directly in the
  shared favorite manager. All matching controls share selected, label, pending,
  disabled, and busy state while one request per game remains in flight. A
  browser-intercepted activation issued one request, synchronized both visible
  representations, and changed the mobile label to “Favorited”.
- Game Edit now uses a shared page header and one flat form surface with Overview,
  Package & installation, Classification, Links & media, and secondary IGDB
  identification sections. Common fields remain visible, selection summaries are
  live, and actions are available at the end of the mobile form. Validation has
  an error summary; all error branches retain location/conflict context. Ordinary
  saves return to Game Details, and dirty conflict/navigation actions are guarded.

The reworked editor was inspected in the live synthetic preview and measured at
desktop and 390 × 844. At 390 px it retained the single 12 px content gutter,
had no nested surfaces or document overflow, hid the duplicate top action row,
and rendered all bottom actions at 44 px. Default-theme canonical and installed
assets were synchronized. The focused verification set passed 130 Python tests,
six JavaScript favorite cases, JavaScript syntax checks, Ruff, and
`git diff --check`. Ember/light-theme, production-scale populated records, setup,
and token-dependent authentication states remain recorded under UI-06 rather
than being claimed as complete.

The missing-artwork follow-up also found that list cards placed the full grid
placeholder inside a 72 px cover. Its monogram crossed the cover boundary and the
small title duplicated the adjacent card title. List placeholders now contain a
compact monogram and hide redundant icon/title content; grid and compact artwork
fallbacks keep the established centered treatment.

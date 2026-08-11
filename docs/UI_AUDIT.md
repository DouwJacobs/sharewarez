# UI audit

Audit date: 2026-08-09  
Branch: `audit/ui-consistency-fixes`  
Application: local WSL development instance at `http://localhost:5006`  
Viewports: desktop 1440 × 1000; mobile 390 × 844  
Theme observed: Evergreen/custom dark-green theme

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

# UI consistency: remaining implementation handoff

Prepared: 7 September 2026. Repository: **WSL `/home/douw/sharewarez`**.

## Task for the implementation agent

Finish the remaining UI consistency work described below. The user wants the same
controls and behavior for equivalent actions across pages, on mobile and desktop.
In particular: **“Open IGDB Page” in the game-card hamburger menu must look and
behave like the other menu rows.** Implement the confirmed items; reproduce the
source-derived risks before choosing a fix. Return commits and verification
evidence so the originating agent can review the result. Do not perform the final
review on behalf of that agent or claim untested states are complete.

Read `AGENTS.md`, `docs/UI_AUDIT.md`, and the Sharewarez UI skill first. This file is
an implementation brief, not a replacement for those contracts.

## Implementation progress

Follow-up fixes (7 September 2026): the confirmed independent-audit defects are
fixed and covered by browser regressions. See the resolution section in
[the audit report](UI_HANDOFF_AUDIT_2026-09-07.md). The broader UI-06 acceptance
matrix is now covered by [the UI-06 verification](UI06_VERIFICATION.md); these
statuses describe the recorded fixtures and checks, not every possible data state.

| Item | Status | Evidence |
| --- | --- | --- |
| UI-01 IGDB menu row | ✅ Complete | Anchor and button rows share `.popup-menu .menu-button`; live fixture measured both at 223.25 × 46.68 px desktop and 188.11 × 46.03 px mobile. |
| UI-02 menu close/focus | ✅ Audit fixes verified | Pending Escape invalidates opening, busy state clears, loaded Escape restores focus, and actions use disclosure semantics. A3/A6 resolved. |
| UI-03 narrow card actions | ✅ Audit fixes verified | Desktop list cover now accommodates both actions; disjoint targets and no document overflow verified at 1440, 390, and 320 px. A2 resolved. |
| UI-04 mobile favorite | ✅ Complete | Mobile and cover controls use the shared manager; one intercepted mobile activation produced one request and synchronized both controls plus the “Favorited” label. |
| UI-05 semantic actions/feedback | ✅ Audit fixes verified | Database removal uses an in-flight guard and disabled/busy state; failure allows retry. Move destinations are native buttons with pending/error recovery. A5 resolved. |
| UI-06 expanded validation | ✅ Complete | 138 route/theme/viewport checks and 27 interaction/contrast scenarios passed; populated views, role menus, Default/Ember/light palette, modal focus, setup, and token flows verified. See UI06_VERIFICATION.md. |
| UI-07 Game Edit rework | ✅ Audit fixes verified | One Boolean validator; Save/Refresh/Enter payloads and repeat-submit guard verified. Identity changes protect dirty drafts; results support keyboard activation; server errors open disclosures and focus linked fields. A1/A4/A6 resolved. |
| UI-08 missing-cover list layout | ✅ Complete | List cards now keep a restrained monogram inside the compact cover and rely on the adjacent title, avoiding duplicated clipped text. |
| UI-10 integration settings shell | ✅ Complete | Integrations, Discord help, legacy settings fallbacks, and scan-filter validation now share the semantic admin header/surface contract. SMTP, IGDB, and Discord actions stack consistently on mobile; Discord's generated test action stays within its own panel. |

## Starting state — preserve completed work

- `13aadda`: responsive control/card standardization and regression coverage.
- `743a7b0`: clear the stale game link/loading title in trailer empty/error states.
- The local branch was `main`, 34 commits ahead of `origin/main` before this
  document. Do not reset or overwrite local history.
- **`VERSION` already had an unrelated user edit. Leave it untouched.** Recheck
  status before editing; another agent may have advanced the repository.
- Canonical theme files are in `sharewarez/setup/default_theme/`. Synchronize each
  changed file into `sharewarez/static/library/themes/default/`. Installed theme
  assets are generally ignored; editing only those files is not an implementation.

Already implemented; do not redo or regress:

1. Library and Favorites share `games/library_cards.html`, the Library stylesheet,
   and `serialize_library_cards()` in `routes_library.py`. Favorites no longer has
   a separate border/panel around its grid. Preserve this shared ownership.
2. Standard `.btn` controls use 42 px desktop / 44 px mobile height, consistent
   radius/type/padding/gap, and no positional hover scaling. Hidden/disabled/focus
   states have shared handling. Menu rows are a different, left-aligned component;
   do not apply centered ordinary-button geometry to them indiscriminately.
3. Request search shells follow shared control height while their inner inputs
   remain transparent and borderless. Select chevrons are theme-aware.
4. Redundant panels were flattened in Themes, Scan Manager, Discord settings,
   Attract Mode, and mobile Newsletter. Authentication headings, labels, and
   action hierarchy were aligned; cover replacement became keyboard-operable.
5. Favorite toggles now share feedback, duplicate-request protection, and
   pressed/busy state for `.favorite-btn` instances. Removing a favorite leaves
   the card available until reload/navigation, allowing immediate reversal.
6. Trailer queries deduplicate ORM identities instead of whole JSON-bearing rows.
   Empty/error states clear stale loading titles and game links.

The baseline passed **87 focused Python tests**, six JavaScript favorite behavior
cases, Ruff, and `git diff --check`. A 98-check sweep covered 49 authenticated URL
variants at desktop/mobile sizes; public forms were also inspected. This is not
proof of every populated state or interaction. Read the limits below.

## UI-01 — Make the IGDB link a real shared menu row (P2, complete)

**User-reported and supported by source inspection.**

Relevant files:

- `sharewarez/templates/games/popup_menu.html`
- `sharewarez/setup/default_theme/css/base.css` — `.menu-item button` and
  `.menu-item a` rules, around lines 1521–1547 at the baseline.
- `sharewarez/setup/default_theme/css/theme-components.css` — menu hover overrides.
- `sharewarez/setup/default_theme/js/popup_menu.js`

The IGDB entry is an `<a class="menu-button">`; other rows are mostly
`<button class="menu-button">`. The base stylesheet gives buttons a full-width
padded row, border/radius, alignment, hover, and focus treatment. The anchor rule
only sets color and text decoration. A shared hover-color rule does not supply
its missing geometry.

Implementation:

- Put row presentation on a scoped shared selector such as
  `.popup-menu .menu-button`, covering anchors and buttons alike. Consolidate the
  conflicting button-only rules instead of adding an isolated IGDB patch.
- Equalize box sizing, full-row width, padding, type, line wrapping, radius,
  left alignment, hover area, and keyboard focus treatment. Use theme tokens.
- Keep anchors as anchors and mutation controls as buttons. Preserve the existing
  HTTP(S) URL guard, `target="_blank"`, and `rel="noopener noreferrer"`.
- Do not add an IGDB-only color, new icon treatment, or centered `.btn` style.

Acceptance:

- With a game that has an IGDB URL, compare IGDB to Edit Details/Download in
  Library, Favorites, and Game Details. The entire row must be clickable.
- Inspect desktop and 390 × 844, Default and Ember. Mobile hit targets must be
  at least 44 px high; wrapped labels must remain contained.
- Tab focus is visible on both element types. The link still opens its expected
  destination in a new tab. Games without a usable URL omit the entry cleanly.
- Add a focused regression for anchor/button parity that would fail on the
  baseline; include rendered measurements, not only a selector-string assertion.

## UI-02 — Unify menu close/focus behavior (audit fixes verified)

`popup_menu.js` handles both `.game-card` and `.game-card-coverimage` when opening
menus or closing them by an outside click. Its Escape handler only resolves
`.game-card` before removing `menu-open` and restoring card controls. This can
leave the Game Details cover in a different state after Escape.

Implementation:

- Reuse one close/restore path for Escape, outside click, trigger toggle, and
  replacement by another card menu. Resolve both card containers consistently.
- Restore hidden favorite/status controls, container classes, `aria-expanded`,
  and trigger focus where appropriate. Avoid moving focus on an ordinary outside
  click that intentionally focuses another control.
- Audit the `aria-haspopup="menu"` contract: the current popup markup lacks a
  complete menu/menuitem keyboard model. Either implement a coherent menu model
  (including enabled-item navigation and Escape) or use appropriate disclosure
  semantics with normal Tab navigation. Do not leave mismatched ARIA promises.
- Preserve the on-demand `/library/game-actions/<uuid>` endpoint, its admin
  boundary, stale-request protection, and event delegation for AJAX cards.

Acceptance:

Exercise open/close on Library, Favorites, and Game Details using keyboard and
pointer, including opening a second card while a request is pending. No stranded
hidden controls, stale overlays, duplicate menus, or lost keyboard focus.

## UI-03 — Resolve narrow compact/list card action collisions (audit fixes verified)

**Needs rendered reproduction; not a completed visual finding.**

Files: `css/games/library_browser.css`, `css/mobile.css`,
`templates/games/library_cards.html`, and the shared menu/status scripts.

The list cover is 72 px wide. Mobile action rules make hamburger/favorite buttons
44 px wide and position them 10 px from opposite edges. Those two targets cannot
fit side-by-side inside that cover. Three-column compact cards may have the same
problem at narrow widths. The previous pass checked ordinary buttons and document
width, not every overlay hit rectangle in every Library view.

- Reproduce grid, compact, and list at 390 px and a narrower supported width.
- Use a shared responsive action arrangement that fits. Keep equivalent actions
  available to touch and keyboard users; do not simply hide favorite/status
  controls without providing an accessible equivalent.
- Preserve cover aspect ratio, title readability, hover preview, saved view
  preferences, and AJAX pagination. Avoid changing all grid card geometry merely
  to accommodate list mode.

Acceptance: action hit rectangles do not overlap each other or intercept the
wrong link; long titles and missing artwork remain readable; view switches and
pagination keep working; no document overflow or duplicate outer mobile gutter.

## UI-04 — Synchronize the mobile Game Details favorite action (P2, complete)

In `templates/games/game_details.html`, the mobile Favorite action is a separate
button that proxies a click to `.favorite-btn-cover`. It is not itself a
`.favorite-btn` with the shared data/state contract. The shared manager updates
its matching controls, but this proxy can retain a static label/icon and lacks
the corresponding pressed/busy representation.

- Give the mobile action a shared state binding or a deliberate rendering hook.
  Keep one API request per activation; avoid double listeners or proxy recursion.
- Reflect selected, pending, success, and failed states consistently with the
  desktop cover control. Keep an accessible name and `aria-pressed` state.
- Retain the existing click-to-toggle behavior and shared feedback. Do not
  reintroduce a Favorites-only confirmation dialog.

Acceptance: toggle from mobile and desktop, verify persisted state after reload,
exercise a slow response and a failed response, and ensure all visible instances
stay synchronized with no duplicate network mutation.

## UI-05 — Finish the semantic action/feedback inventory (audit fixes verified)

The prior pass corrected several legacy colors; it did not exhaustively review
all dynamic controls. Concrete starting points:

- `templates/admin/admin_manage_users.html`: table Edit buttons still use
  `btn-primary edit-user`, while comparable edit actions elsewhere are secondary.
- `templates/games/popup_menu.html`: destructive database/disk removal rows share
  ordinary menu treatment. Introduce a shared semantic destructive-row modifier
  if needed, without changing menu geometry or confirmation safeguards.
- `js/popup_menu.js`: some asynchronous actions still inject literal colors and
  use `alert()` while other shared actions use the existing notification system.

Inventory equivalent actions before changing them. Preserve a meaningful primary
submission per region, secondary alternatives/navigation, and danger treatment
for destructive actions. “Cancel editing” and “cancel a running job” have different
consequences; do not mechanically recolor every label containing Cancel.

Standardize pending/disabled/retry/error feedback for equivalent operations,
preserving all CSRF tokens, action URLs, permission checks, confirmations, and
JavaScript hooks. Keep native confirmation behavior unless a coherent shared
replacement is implemented and tested. Do not send real notifications or perform
real deletions merely to verify presentation.

## UI-06 — Complete the populated-state and theme validation gaps (verified)

Completed 8 September 2026. See [UI06_VERIFICATION.md](UI06_VERIFICATION.md) for
fixtures, findings, fixes, rendered evidence, and precise verification scope.

These are **verification tasks**, not claims that every listed screen is broken.
Fix concrete defects found and record evidence.

- Populated request/issue detail views, collection edit/detail variants, invitation
  rows, and non-empty image galleries were not fully exercised in the earlier
  fixture. Include long names, missing artwork, empty/error/loading states, and
  tables wide enough to require internal scrolling.
- Test every Library layout plus populated Favorites and Game Details, including
  the shared menu's full administrator item set and a member's reduced item set.
- Check all changed controls in Default and Ember. No light theme was available
  previously; use an isolated light/high-luminance test palette if available, or
  explicitly record that coverage gap. Never overwrite the user's custom theme.
- Verify focus visibility, keyboard traversal, touch targets, reduced motion,
  modal containment, and bottom-navigation clearance. A width-only scan cannot
  detect an invisible/overlapping action or a focus-restoration defect.
- Initial setup and token-dependent confirmation/reset completion pages still
  need isolated fixtures for an end-to-end review. Do not reset the real instance
  or change real credentials to create those fixtures.

## UI-07 — Rework Game Edit around everyday editing (audit fixes verified)

The user explicitly wants `/game_edit/<game_uuid>` to fit the shared UI and feel
smoother to use. Treat this as a focused editor rework, not merely a button-color
fix. Prioritize it alongside UI-01. Keep identification available without making
it dominate ordinary metadata editing.

Relevant sources:

- `sharewarez/templates/admin/admin_game_identify.html` (shared by editing and
  identification workflows; there is no separate `game_edit.html`).
- `sharewarez/setup/default_theme/css/admin/admin_game_identify.css`
- `sharewarez/setup/default_theme/js/admin_game_identify.js`
- `sharewarez/routes_games_ext/edit.py`, `sharewarez/forms.py`
- `docs/METADATA_PROVENANCE.md`, `tests/test_routes_games_ext_edit.py`, and
  `tests/test_metadata_provenance.py`.

Observed baseline and source findings:

- A fresh desktop inspection in the synthetic port-5008 preview shows a large
  generic heading, a deeply inset essentials region, and prominent ID/name
  lookup buttons. The game identity and everyday editing tasks get less emphasis.
  This follow-up did not repeat the mobile inspection; require it below.
- Most metadata is hidden behind one generic Details collapse. Save actions are
  only at the top, making the expanded form cumbersome to finish.
- The stylesheet retains global `label`, `.form-control`, `.alert`, and other
  overrides, plus layers of legacy surface rules. The final flattening selectors
  omit `.essential-info`; the live essentials region still has its own fill and
  inset within the page surface. Consolidate ownership instead of stacking more
  overrides.
- Ordinary Save redirects to Library, while Save & Refresh redirects to Game
  Details. Cancel always returns to Library. Several early error render branches
  omit library/platform/conflict context supplied by the normal render path.
- Conflict resolution buttons submit the main editor form to a separate endpoint
  that redirects without saving other edits. The shared submit handler preserves
  `action` but disables all submit buttons without preserving `resolution`.
  Reproduce and fix this payload risk; do not let conflict review discard edits.
- Initial validation disables only the first submit button. The submit handler's
  early `return` does not cancel submission. Verify equivalent validation for
  Save, Save & Refresh, and Enter before changing the presentation.

Target layout and interaction:

1. Use the shared page header with **Edit game**, the current game name, compact
   library/platform context, and secondary Back to game navigation. Use the
   shared rail and one main surface with flat sections, quiet dividers, and
   normal label typography. Remove route-wide restyling of shared controls.
2. Present clearly named groups: **Overview** (name, summary, storyline, release
   metadata, credits), **Package & installation** (version, edition, instructions,
   disk path), **Classification** (genres, modes, themes, platforms, perspectives,
   tags), and **Links & media** (existing URL/video fields plus navigation to the
   image editor). Use two columns only for short related fields; prose remains
   full-width. Keep all existing fields and their submission names.
3. Put **IGDB identification** in its own secondary section with current ID and
   explicit Search IGDB / Look up ID / Custom game actions. Explain when choosing
   another identity populates fields and triggers replacement images on save.
   Preserve the add/unmatched/re-identify workflows through mode-aware shared
   partials or equivalent reuse; their primary task differs from editing.
4. Replace the catch-all Details toggle with meaningful section headings and,
   only where useful, accessible disclosures. Keep common editing fields visible.
   Classification controls should summarize selected values/counts and remain
   usable with many options, touch, and keyboard. Do not force checkbox lists
   into ordinary single-select geometry.
5. Keep **Save changes** primary and **Save & refresh metadata** secondary, with
   concise explanation of manual-value preservation and refresh behavior. Make
   actions reachable at the end of the form as well as the beginning using the
   same labels/state. A sticky action area is optional only if it clears mobile
   bottom navigation and never covers focused inputs or errors.
6. Make Save, Save & Refresh, Cancel, and Back return predictably to the edited
   game by default. If preserving entry context, use one validated same-origin
   return destination across those actions. Protect dirty edits before leaving
   through navigation or identity/conflict operations; do not prompt on a clean
   form or a successful intentional save.
7. Show inline errors and a linked error summary; open any section containing an
   invalid field and focus the first actionable error. Preserve submitted values,
   selected classifications, game identity, library/platform labels, and conflict
   context on every server error path. Factor a common render-context helper if
   appropriate. Keep errors readable without relying only on color.
8. Prevent duplicate submits and expose accurate pending/failure state for each
   action, including Enter submission. Ensure disabled controls do not remove
   required action/resolution values from the payload. A failed save must remain
   recoverable; a successful save followed by a failed refresh must say so.
9. Keep provider-conflict review distinct from unsaved form editing. Use a
   deliberate staged or guarded resolution flow; never silently lose the draft.
   Preserve field ownership, provider candidates, CSRF, administrator checks,
   path validation, scan restrictions, and re-identification image-refresh order.

Acceptance and review evidence:

- Capture before/after desktop and 390 × 844 views with a populated game, expanded
  sections, long names/paths, several classifications, and provider conflicts.
  Check Default and Ember, shared control heights, one mobile gutter, no nested
  elevated form panels, no overflow, and bottom-navigation clearance.
- Exercise ordinary editing without opening identification; users can find a
  field, save it, and return to the same game without excessive scrolling.
- Verify Save, Save & Refresh, Enter, Cancel/Back, dirty navigation, custom-game
  mode, IGDB lookup success/empty/failure, and keyboard selection of a result.
  Stub external calls and use disposable records for mutations.
- Cover invalid input inside a collapsed section, scan-blocked saving, database
  failure, and refresh failure after a successful save. Confirm values and page
  context survive. No stuck blocking spinner or bypass via the secondary action.
- Test both conflict resolutions with unrelated dirty fields and confirm the
  intended resolution reaches the server. Assert manual metadata survives refresh
  and identity replacement still uses the correct image-refresh ordering.
- Run edit-route/provenance regressions plus relevant UI/accessibility tests; add
  behavior regressions for confirmed submission/error-state defects. Inspect the
  shared template's identification and unmatched variants for regressions too.

## Implementation and verification workflow

1. Inspect the current branch/worktree. Work in WSL, activate the Sharewarez Python
   environment, and read the current guidance. Do not use the Windows checkout.
2. Use existing shared components and preserve the single mobile gutter owned by
   `#content`. Keep major surfaces as siblings; do not reintroduce the Favorites
   grid frame or equally elevated nested panels.
3. Prioritize UI-01 and the user-requested UI-07 editor rework, then complete
   UI-02 through UI-04 and the verified UI-05 findings in coherent changes. Do not turn this into a new frontend framework or broad visual
   redesign. Reuse the current Bootstrap/Jinja/JavaScript infrastructure.
4. Use Computer Use to inspect real rendered routes at default desktop,
   1440 × 1000, and 390 × 844, plus narrow compact/list checks. Allow stylesheet
   loading to settle before recording measurements. Reset viewport overrides.
5. Run targeted existing tests and add behavior regressions for newly fixed
   failures. Useful starting points:

   ```text
   tests/test_ui_control_contract.py
   tests/test_ui_polish_contract.py
   tests/test_mobile_navigation.py
   tests/test_accessibility_audit.py
   tests/test_ui_consistency_routes.py
   tests/test_routes_library.py
   tests/test_routes_apis_user.py
   tests/favorites_manager.test.cjs
   ```

   Use an explicitly isolated PostgreSQL `TEST_DATABASE_URL`; never point tests
   at the populated library database. The Node test can run directly with Node
   on Windows against the WSL UNC path if WSL has no Node installation.
6. Run Ruff on changed Python, `git diff --check`, JavaScript syntax/behavior tests,
   and verify canonical/installed asset equality. Update `docs/UI_AUDIT.md` with
   actual coverage and remaining limitations. Commit only the relevant changes.
7. Return the review package below. Do not bump VERSION, publish a release, push
   Docker images, or deploy; these are outside this UI implementation brief.

The previous preview used port 5008 and a disposable Docker database named
`sharewarez-ui-audit-db` on port 55441. It contained synthetic data. Do not assume
it is still running or empty. Never reuse its database as a destructive test
fixture without first identifying what is in it. The normal port-5006 server was
offline during the audit; this is an environment observation, not a UI defect.

## Required review package

Return:

- Commit hashes and a short mapping from UI-01…UI-07 to changes or explicit gaps.
- Before/after evidence for the IGDB row and compact/list action arrangement.
- Desktop/mobile screenshots for Library, Favorites, Game Details, and affected
  admin pages and the reworked Game Edit form, with theme and viewport recorded.
- Measured row heights/hit bounds and keyboard/focus results for the shared menu.
- Exact tests run and outcomes; list anything blocked or intentionally untested.
- Confirmation that equivalent link/button menu rows share one style contract,
  the Favorites border fix remains intact, and the user's VERSION edit survives.

The originating agent will review the commits, inspect the rendered result,
re-run relevant regressions, and report any remaining issues to the user.

## UI-08 — Keep missing artwork contained in list cards (complete)

The list layout previously reused the full grid placeholder inside a 72 px cover.
Its large monogram overflowed the artwork boundary, while the icon and small title
duplicated information already displayed beside the cover. List placeholders now
hide the redundant icon/title, constrain overflow, and use a compact monogram.
Grid and compact placeholders retain their full centered treatment.

## UI-09 — Show one overall IGDB image-refresh state (complete)

The image editor now shows one responsive progress panel for the complete refresh,
with a single percentage bar, phase label, and processed/downloaded/failed totals.
The cached progress contract exposes the same overall state to polling clients and
retains a useful completion summary. Error messages remain in the panel and allow
the administrator to retry.

Media discovery remains API-only. For test game `282831` (The Blood of Dawnwalker),
IGDB's public game and artwork endpoints return the cover, 15 screenshots, and 9
artworks, but omit the two standalone logos shown by IGDB's press-kit page. Those
website-only assets cannot be discovered through the supported API, so the editor
states when no standalone logos were returned and keeps manual logo upload available.

## UI-10 — Standardize integration settings and legacy fallbacks (complete)

The live Integrations workspace now imports the shared administrator page header
and relies on `.app-page` for its outer gutter. SMTP, IGDB, and Discord use the same
action-row contract, with full-width stacked buttons at the mobile breakpoint and
the normal shared button geometry on desktop. Their route styles are scoped to the
owning panel and use theme tokens for surfaces, borders, and text.

The Discord help page and the legacy direct-route templates use one semantic
`main`, one H1 header, and one `app-surface`. Discord JavaScript is resolved through
`theme_asset` and only inserts Test webhook in a Discord action row. The invalid
scan-filter POST fallback uses the same shell and converts its desktop table into
labeled mobile records.

Verification: the accessibility audit passed 88 templates; 19 UI source-contract
tests and 96 focused Discord, IGDB, SMTP, and filter route tests passed. The live
disposable preview was inspected in Default and Ember at desktop and mobile
breakpoints, including each integration tab, action wrapping, notification cards,
and Discord help content.
